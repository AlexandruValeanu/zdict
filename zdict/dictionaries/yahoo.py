import json
import re

from collections import deque

from bs4 import BeautifulSoup

from zdict.dictionary import DictBase
from zdict.exceptions import NotFoundError
from zdict.models import Record


def text(x):
    return x.text


def foreach(f: 'function', i: iter) -> None:
    deque(map(f, i), 0)


class YahooDict(DictBase):

    API = 'https://tw.dictionary.yahoo.com/dictionary?p={word}'

    @property
    def provider(self):
        return 'yahoo'

    @property
    def title(self):
        return 'Yahoo Dictionary'

    def _get_url(self, word) -> str:
        return self.API.format(word=word)

    def show(self, record: Record):
        content = json.loads(record.content)
        getattr(self, 'show_v{}'.format(content.get('version', 1)))(content)

    def show_v1(self, content):  # legacy
        # print word
        self.color.print(content['word'], 'yellow')

        # print pronounce
        for k, v in content.get('pronounce', []):
            self.color.print(k, end='')
            self.color.print(v, 'lwhite', end=' ')
        print()

        # print explain
        main_explanations = content.get('explain', [])
        if self.args.verbose:
            main_explanations.extend(content.get('verbose', []))

        for speech in main_explanations:
            self.color.print(speech[0], 'lred')
            for meaning in speech[1:]:
                self.color.print(
                    '{text}'.format(text=meaning[0]),
                    'org',
                    indent=2
                )
                for sentence in meaning[1:]:
                    if sentence:
                        print(' ' * 4, end='')
                        for i, s in enumerate(sentence.split('*')):
                            self.color.print(
                                s,
                                'lindigo' if i % 2 else 'indigo',
                                end=''
                            )
                        print()
        print()

    def show_v2(self, content):
        self.show_v2_summary(content['summary'])
        self.show_v2_explain(content.get('explain'))
        self.show_v2_verbose(content.get('verbose'))
        print()

    def show_v2_summary(self, summary):
        # word
        self.color.print(summary['word'], 'yellow')
        # pronounce
        pronounce = summary.get('pronounce', [])
        for k, v in pronounce:
            self.color.print(k, end='')
            self.color.print(v, 'lwhite', end=' ')
        print() if pronounce else None
        # explain
        indent = True
        for (t, s) in summary.get('explain', []):
            if t == 'explain':
                self.color.print(s, indent=2 * indent)
                indent = True
            elif t == 'pos':
                self.color.print(s, 'lred', end=' ', indent=2 * indent)
                indent = False
        # grammar
        grammar = summary.get('grammar', [])
        print() if grammar else None
        for s in grammar:
            self.color.print(s, indent=2)

    def show_v2_explain(self, explain):
        if not explain:
            return

        print()
        # explain
        for exp in explain:
            type_ = exp['type']
            if type_ == 'PoS':
                self.color.print(exp['text'], 'lred')

            elif type_ == 'item':
                self.color.print(exp['text'], indent=2)
                sentence = exp.get('sentence')

                if not sentence:
                    continue

                indent = True
                for s in sentence:
                    if isinstance(s, str) and s != '\n':
                        self.color.print(s, 'indigo', end='',
                                         indent=indent * 4)
                    elif isinstance(s, list) and s[0] == 'b':
                        self.color.print(s[1], 'lindigo', end='',
                                         indent=indent * 4)
                    elif s == '\n':
                        print()
                        indent = True
                        continue

                    indent = False

    def show_v2_verbose(self, verbose):
        if not self.args.verbose:
            return
        if not verbose:
            return

        print()
        color = {'title': 'lred', 'explain': 'org', 'item': 'indigo'}
        indent = {'title': 0, 'explain': 2, 'item': 4}
        foreach(
            lambda x: self.color.print(x[1], color[x[0]], indent[x[0]]),
            verbose)

    def query(self, word: str):
        webpage = self._get_raw(word)
        data = BeautifulSoup(webpage, "html.parser")
        content = {}

        # Please bump version if the format changes again.
        # the `show` function will act with respect to version number.

        content['version'] = 2

        # Here are details of each version.
        #
        # The original one, in the old era, there wasn't any concept of
        # version number:
        # content = {
        #     'word': ...,
        #     'pronounce': ...,
        #     'sound': (optional),
        #     'explain': [...],
        #     'verbose': [...],
        # }
        #
        # Verion 2, yahoo dictionary content is provided by Dy.eye
        # at that moment:
        # content = {
        #     'version': 2,
        #     'summary': {
        #         'word': ...,
        #         'pronounce': [('KK', '...'), (...)],  // optional.
        #                                               // e.g. 'google'
        #         'explain': [(optional)],  # 'hospitalized' is summary-only
        #         'grammar': [(optional)],
        #     },
        #     'explain': [...],
        #     'verbose': [(optional)],
        # }

        # Construct summary (required)
        try:
            content['summary'] = self.parse_summary(data, word)
        except AttributeError:
            raise NotFoundError(word)

        # Handle explain (required)
        try:
            content['explain'] = self.parse_explain(data)
        except IndexError:
            raise NotFoundError(word)

        # Extract verbose (optional)
        content['verbose'] = self.parse_verbose(data)

        record = Record(
            word=word,
            content=json.dumps(content),
            source=self.provider,
        )
        return record

    def parse_summary(self, data, word):
        def gete(x: 'bs4 node'):
            def f(ks):
                return (
                    'pos' if 'pos_button' in ks else
                    'explain' if 'dictionaryExplanation' in ks else
                    '?')

            return [
                (f(m.attrs['class']), m.text)
                for n in x.select('ul > li') for m in n.select('div')]

        def getp(p):
            return list(map(
                lambda x: re.match('(.*)(\[.*\])', x).groups(),
                p.find('ul').text.strip().split()))

        def getg(d):
            s = ('div#web ol.searchCenterMiddle '
                 'div.dictionaryWordCard > ul > li')
            return list(map(text, data.select(s)))

        node = data.select_one('div#web ol.searchCenterMiddle > li > div')
        node = node.select('> div')

        p = None  # optional
        if len(node) == 6:    # e.g. "metadata"
            _, w, p, _, _, e = node
        elif len(node) == 5:
            _, w, p, _, e = node
        elif len(node) == 4:  # e.g. "hold on"
            _, w, _, e = node
        elif len(node) == 3:  # e.g. "google"
            _, w, e = node
        elif len(node) <= 2:  # e.g. "fabor"
            raise NotFoundError(word)

        return {
            'word': w.find('span').text.strip(),
            'pronounce': getp(p) if p else [],  # optional
            'explain': gete(e),
            'grammar': getg(data),  # optional
        }

    def parse_explain(self, data):
        def getitem(node) -> {'type': 'item', 'text': '...'}:
            s = node.select_one('span')
            exp = {
                'type': 'item',
                'text': s.text,
                'sentence': [],
            }

            for s in node.select('p'):
                sentence = list(map(
                    lambda x: ('b', x.text) if x.name == 'b' else str(x),
                    s.span.contents))
                if isinstance(sentence[-1], str):
                    hd, _, tl = sentence.pop().rpartition(' ')
                    sentence.extend([hd, '\n', tl])
                sentence.append('\n')
                exp['sentence'].extend(sentence)

            return exp

        ret = []
        nodes = data.select('div.tab-content-explanation ul li')

        for node in nodes:
            if re.match('\d', node.text.strip()):
                exp = getitem(node)
            else:
                exp = {
                    'type': 'PoS',  # part of speech
                    'text': node.text.strip(),
                }
            ret.append(exp)

        return ret

    def parse_verbose(self, data):
        ret = []
        nodes = data.select_one('div.tab-content-synonyms')
        for node in nodes if nodes else []:
            name = node.name
            if name == 'div':
                if node.span is None:
                    continue

                cls = node.span.attrs.get('class')
                if cls is None:
                    continue

                s = node.span.text.strip()
                'fw-xl' in cls and ret.append(('title', s))
                'fw-500' in cls and ret.append(('explain', s))

            elif name == 'ul':
                for li in node.select('> li'):
                    ret.append(('item', li.span.text))
        return ret
