#!/usr/bin/env python3

import sqlite3
import shutil
import sys
from os import path
from contextlib import contextmanager
import json
from itertools import groupby
from functools import lru_cache
import shutil
import math
import re
import time


@contextmanager
def dbopen(dbdir, dbfile):
    db = None
    try:
        db = sqlite3.connect(path.expanduser(path.join(dbdir, dbfile)))
        yield db
    finally:
        if db:
            db.close()

def list_profiles(anki_dir='~/Anki'):
    with dbopen(anki_dir, 'prefs.db') as db:
        return { name: path.join(anki_dir, name)
                for name, in db.execute('SELECT name FROM profiles WHERE name != "_global"').fetchall() }

def list_decks(db_file):
    db = sqlite3.connect(db_file)
    if db.execute('SELECT COUNT(*) FROM col').fetchone() > (1,):
        raise UserWarning('Profile contains more than one collection.')
    decks = json.loads(db.execute('SELECT decks FROM col LIMIT 1').fetchone()[0])

    # NOTE: The deck_id check for the special "Default" deck is a bit heuristic here. This deck is created when the
    # profile is initialized and as such AFAICT will always end up with the sqlite ID 1. We can't reliably use the
    # deck name, as that one is just "Default", and nothing prevents anyone from naming a regular deck thus. This
    # sqlite ID hack is also what Anki itself uses.

    if len({ data['name'] for data in decks.values() }) != len(decks):
        raise UserWarning('Collection contains decks with duplicate names')

    res = [ (['<everything>'] + ([] if deck_id == '1' else data['name'].split('::')), deck_id)
            for deck_id, data
            in decks.items()
        ]
    
    build_decks = lambda res: [
            Deck(db,
                 key,
                 group[0][1], # the group's first element is the one with the shortest name, i.e. the super-deck
                 build_decks( [ (n[1:],did) for n,did in group[1:] ] )
            )
            for key,group
            in (
                (key, list(group))
                for key,group
                in groupby(
                    res,
                    lambda e: e[0][0]
                )
            )
        ]

    return build_decks(sorted(res))[0]

class CmdlineTreeMixin:
    def print_tree(self, leaf_lambda=lambda t: '', indent='', prefix='', idx=0):
        print('\033[{ca}m{prefix}⟪\033[{cb}m{idx}\033[{ca}m⟫\033[{cc}m {name}'.format(
            prefix=prefix,
            idx=idx,
            name=self._cmdline_name,
            ca='33', cb='93', cc='0') +
            leaf_lambda(self))
        idx += 1
        if self._cmdline_children:
            for c in self._cmdline_children[:-1]:
                idx = c.print_tree(leaf_lambda, indent+'│   ', indent+'├──', idx)
            idx = self._cmdline_children[-1].print_tree(leaf_lambda, indent+'    ', indent+'└──', idx)
        return idx

    def child_by_idx(self, idx):
        rv = self._child_by_idx(idx)
        if type(rv) is int:
            raise IndexError('Tree child index out of range')
        return rv

    def _child_by_idx(self, idx):
        if idx == 0:
            return self
        idx -= 1
        for c in self._cmdline_children:
            idx = c._child_by_idx(idx)
            if type(idx) is not int:
                break
        return idx


class Deck(CmdlineTreeMixin):
    def __init__(self, db, name, own_id, subdecks):
        self.db = db
        self.name = self._cmdline_name = name
        self.own_id = own_id
        # NOTE: If the list of subgroups would be changed, this value would have to be updated.
        self.subdecks = self._cmdline_children = subdecks
        self.ids = {own_id} if own_id else set()
        for d in subdecks:
            self.ids |= d.ids
        self.subs_by_name = { d.name: d for d in subdecks }

    def _idhack(self, query):
        return query.format(ids=','.join(['?']*len(self.ids)))

    def _iexec(self, query, args=tuple()):
        return self.db.execute(self._idhack(query), (*self.ids, *args))

    def mature_avg_reviews(self, cutoff_interval: 'days'=21):
        return self._iexec('SELECT AVG(cnt) FROM ('
                'SELECT COUNT(*) as cnt FROM revlog JOIN cards ON cid=cards.id '
                'WHERE did IN ({ids}) AND cards.ivl > ? GROUP BY cid)', (cutoff_interval,)).fetchone()[0]

    def total_reviews(self):
        return self._iexec('SELECT SUM(cnt) FROM ('
                'SELECT COUNT(*) as cnt FROM revlog JOIN cards ON cid=cards.id '
                'WHERE did IN ({ids}) GROUP BY cid)').fetchone()[0]

    def revision_histogram(self):
        return self._iexec('SELECT cnt, COUNT(*) FROM ('
                'SELECT COUNT(*) AS cnt FROM revlog JOIN cards ON cid=cards.id '
                'WHERE did IN ({ids}) GROUP BY cid'
            ') GROUP BY cnt').fetchall()

    def generate_practice_sheet(self, timespan, kanji, hint_fields):
        import bs4

        models = json.loads(self.db.execute('SELECT models FROM col').fetchone()[0])
        fieldnames = {
                int(model_id): [
                    field['name']
                    for field in model['flds']
                ] for model_id, model in models.items()
            }
        models = self._iexec(
                    'SELECT DISTINCT mid FROM cards JOIN notes ON cards.nid=notes.id WHERE cards.did IN ({ids})'
                ).fetchall()

        first_model, = models[0]
        common = fieldnames[first_model]
        anywhere = fieldnames[first_model]
        for model, in models[1:]:
            names = set(fieldnames[model])
            anywhere |= names
            common   &= names

        common_color = 93
        msg  = 'Field names (\x1b[{}mcommon to all cards\x1b[0m):\n* '.format(common_color)+'\n* '.join(
                    '\x1b[{}m{}\x1b[0m'.format(common_color, n) if n in common else n
                for n in sorted(anywhere))

        hint_fields = hint_fields.split(',')
        if not kanji in anywhere:
            raise IndexError('Cannot find kanji field name {} in deck models'.format(kanji))
        for hint in hint_fields:
            if hint not in anywhere:
                raise IndexError('Cannot find hint field name {} in deck models'.format(hint))

        cards = self._iexec(
                'SELECT DISTINCT mid, flds FROM revlog '
                'JOIN cards ON revlog.cid=cards.id '
                'JOIN notes ON cards.nid=notes.id '
                'WHERE cards.did IN ({ids}) '
                'AND revlog.id>?', ((time.time()-timespan)*1000,))

        rv = []
        for model_id, fields in cards:
            names = fieldnames[model_id]
            fields = dict(zip(names, fields.split('\x1f')))

            kanji_value = fields[kanji]
            if re.search('[a-zA-Z]', kanji_value):
                continue # likely a non-unicode kanji replaced by an image

            clean = lambda val: bs4.BeautifulSoup(val, 'lxml').text.replace(kanji_value, '█').strip().replace('\n', '')
            hint_value = [ clean(fields[name]) for name in hint_fields ]

            rv.append((kanji_value, hint_value))
        return rv, msg

    def __repr__(self):
        return '<Deck {} "{}", {} subdecks>'.format(self.own_id, self.name, len(self.subdecks))

def generate_latex(f, vals):
    for kanji, hints in vals:
        f.write('\\practiceentry{{{}}}{{\n    {}\n}}\n'.format(
            kanji,
            '\n    '.join(
                '\\hint{{{}}}'.format(hint) for hint in hints)))
    return 'Wrote {} kanji'.format(len(vals))

strip_escapes = lambda s: re.sub('\033\\[[^m]+m', '', s)
term_width = lambda s: len(strip_escapes(s))
bar = lambda val, step: '█'*int(val/step) + ' ▏▎▍▌▋▊▉██'[round((val/step)%1*8)]

def pretty_histogram(data, cfmt='{}'):
    ca, cb, cc, cs, ct, cv = '37', '0', '93', '93', '37', '31'
    vals, counts = zip(*data)
    clen,   vlen = max(map(len, map(cfmt.format, counts))), max(map(len, map(str, vals)))
    cols,   rows = shutil.get_terminal_size()
    fmt      = '\033[{cv}m{{:>{vlen}}}\033[{ca}m│\033[{cc}m{{:<{clen}}}\033[{ca}m│\033[{cb}m{{}}'.format(
            cv=cv, ca=ca, cc=cc, cb=cb,
            vlen=vlen, clen=clen)
    # This will break for one billion reviews or more in one bin
    tick_fmt = '\033[{cs}m{{:>9}}\033[{ct}m'.format(cs=cs, ct=ct)
    tickw    = term_width(tick_fmt.format(0))+1 # +1 for pointer character added below
    graphw   = cols - term_width(fmt.format(0, 0, ''))
    ticks    = int(graphw/tickw)
    grid     = (' '*(tickw-1) + '│')*ticks
    min_step = max(counts)/ticks
    foo      = 10**int(math.log10(min_step))
    sensible_step = int((math.ceil(min_step/foo)) * foo)
    step     = sensible_step/tickw

    graphlines = [ fmt.format(val, cfmt.format(count), bar(count, step) + '\033[{ct}m'.format(ct=ct) + grid[int(count/step)+1:])
            for val, count in data ]
    scale = lambda c: fmt.format('x', '#', ((tick_fmt+c)*ticks).format(*((i+1)*sensible_step for i in range(ticks))))

#    chunksize = int(rows/2)
    chunksize = rows-2

    print(scale('┐'))
    while graphlines:
        print('\n'.join(graphlines[:chunksize]))
        graphlines = graphlines[chunksize:]
        if graphlines:
            print(scale('┤'))
    print(scale('┘'))
    print('\033[0m')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-a', '--ankidir', default='~/Anki')
    parser.add_argument('-p', '--profile')
    parser.add_argument('-b', '--database')
    parser.add_argument('-d', '--decks', default='0')
    sub = parser.add_subparsers(dest='cmd', metavar='CMD')
    sub.required = True

    def subcmd(func):
        subparser = sub.add_parser(func.__name__.strip('_'))
        subparser.set_defaults(func=func)
        func.parser = subparser
        return func
    
    @subcmd
    def _list_profiles(args, **_):
        pros = list_profiles(args.ankidir)
        for name, path in pros.items():
            print('{}: {}'.format(name, path))

    @subcmd
    def _list_decks(db_file, **_):
        list_decks(db_file).print_tree()

    @subcmd
    def _print_deck_ids(deck, **_):
        print('\n'.join(deck.ids))

    @subcmd
    def _mature_avg_reviews(args, deck, **_):
        if args.tree:
            deck.print_tree(lambda t: ' \033[96mavg=\033[93m{:.3f}'.format(t.mature_avg_reviews(args.cutoff) or 0))
        else:
            print('Average review count of mature cards for {}: {:.3f}'.format(
                ', '.join(d.name for d in deck.subdecks), deck.mature_avg_reviews(args.cutoff) or 0))
    _mature_avg_reviews.parser.add_argument('-c', '--cutoff', default=21)
    _mature_avg_reviews.parser.add_argument('-t', '--tree', action='store_true')

    @subcmd
    def _total_reviews(args, deck, **_):
        if args.tree:
            deck.print_tree(lambda t: ' \033[96mtot=\033[93m{}'.format(t.total_reviews() or 0))
        else:
            print('Total review count for {}: {}'.format(
                ', '.join(d.name for d in deck.subdecks), deck.total_reviews() or 0))
    _total_reviews.parser.add_argument('-t', '--tree', action='store_true')

    @subcmd
    def _revision_histogram(deck, **_):
        pretty_histogram(deck.revision_histogram())

    @subcmd
    def _generate_practice_sheet(deck, args, **_):
        match = re.match('([0-9]+)([mhdwMy])', args.timespan)
        if not match:
            print('Allowed time format: [number][mhdwMy]')
            _generate_practice_sheet.parser.print_help()
            return
        timespan = int(match.group(1)) * {
                'm': 60,
                'h': 3600,
                'd': 86400,
                'w': 86400*7,
                'M': 86400*30,
                'y': int(86400*365.25)}[match.group(2)]
        rv, msg = deck.generate_practice_sheet(timespan, args.kanji, args.hints)
        print(msg)
        print(generate_latex(args.outfile, rv))
    _generate_practice_sheet.parser.add_argument('-t', '--timespan', default='1w', nargs='?')
    _generate_practice_sheet.parser.add_argument('-k', '--kanji', default='Kanji', nargs='?', help='Name of note field containing kanji') 
    _generate_practice_sheet.parser.add_argument('-x', '--hints', default='Meaning,Onyomi,First kunyomi', help='Comma-separated names of note fields to put on output as hints') 
    _generate_practice_sheet.parser.add_argument('outfile', type=argparse.FileType('w'))
    sub.help = 'Available commands:\n* {}'.format(
            '\n* '.join(sub.choices.keys()))
    args = parser.parse_args()

    try:
        if args.database:
            db_file, pro = args.database, None
        else:
            pros = list_profiles(args.ankidir)
            pro = pros[args.profile] if args.profile else sorted(pros.items())[0][1]
            db_file = path.expanduser(path.join(pro, 'collection.anki2'))

        if not path.isfile(db_file):
            raise ValueError('Database file not found at {}'.format(db_file))
        root = list_decks(db_file)

        deck = Deck(root.db, '<query>', None, [ root.child_by_idx(int(idx)) for idx in args.decks.split(',') ])
        if args.func:
            args.func(root=root, db_file=db_file, args=args, pro=pro, deck=deck)
        else:
            print('Unknown sub-command.')
    except Exception as e:
        import traceback
        traceback.print_exc()
        print()
        parser.print_help()
        sys.exit(2)

