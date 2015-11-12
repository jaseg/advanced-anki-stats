#!/usr/bin/env python3

import sqlite3
import shutil
from os import path
from contextlib import contextmanager
import json
from itertools import groupby
from functools import lru_cache
import shutil
import math
import re


@contextmanager
def dbopen(dbdir, dbfile):
    try:
        db = sqlite3.connect(path.expanduser(path.join(dbdir, dbfile)))
        yield db
    finally:
        db.close()

def list_profiles(anki_dir='~/Anki'):
    with dbopen(anki_dir, 'prefs.db') as db:
        return { name: path.join(anki_dir, name)
                for name, in db.execute('SELECT name FROM profiles WHERE name != "_global"').fetchall() }

def list_decks(profile_dir='~/Anki/User 1'):
    db = sqlite3.connect(path.expanduser(path.join(profile_dir, 'collection.anki2')))
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
    def print_tree(self, indent='', prefix='', idx=0):
        print('\033[{ca}m{prefix}⟪\033[{cb}m{idx}\033[{ca}m⟫\033[{cc}m {name}'.format(
            prefix=prefix,
            idx=idx,
            name=self._cmdline_name,
            ca='33', cb='93', cc='0'))
        idx += 1
        if self._cmdline_children:
            for c in self._cmdline_children[:-1]:
                idx = c.print_tree(indent+'│   ', indent+'├──', idx)
            idx = self._cmdline_children[-1].print_tree(indent+'    ', indent+'└──', idx)
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

    def _idhack(self, query):
        return query.format(ids=','.join(['?']*len(self.ids)))

    def mature_avg_reviews(self, cutoff_interval: 'days'=21):
        return self.db.execute(self._idhack('SELECT AVG(cnt) FROM ('
                'SELECT COUNT(*) as cnt FROM revlog JOIN cards ON cid=cards.id '
                'WHERE did IN ({ids}) AND cards.ivl > ? GROUP BY cid)'), (*self.ids, cutoff_interval)).fetchone()[0]

    def revision_histogram(self):
        return self.db.execute(self._idhack('SELECT cnt, COUNT(*) FROM ('
                'SELECT COUNT(*) AS cnt FROM revlog JOIN cards ON cid=cards.id '
                'WHERE did IN ({ids}) GROUP BY cid'
            ') GROUP BY cnt'), tuple(self.ids)).fetchall()


def pretty_histogram(data):
    ca, cb, cc, cs, ct, cv = '37', '0', '93', '93', '37', '31'
    vals, counts = zip(*data)
    clen,   vlen = max(map(len, map(str, counts))), max(map(len, map(str, vals)))
    cols,   rows = shutil.get_terminal_size()
    fmt    = '\033[{cv}m{{:>{vlen}}}\033[{ca}m│\033[{cc}m{{:<{clen}}}\033[{ca}m│\033[{cb}m{{}}'.format(cv=cv, ca=ca, cc=cc, cb=cb,
            vlen=vlen, clen=clen)
    tick_fmt = '\033[{cs}m{{:>9}}\033[{ct}m┐'.format(cs=cs, ct=ct)
    tickw = 10
    graphw = cols - len(re.sub('\033[^m]m', '', fmt.format(0, 0, '')))
    # This will break for one billion reviews or more in one bin
    ticks = int(graphw/tickw)
    min_step = max(counts)/ticks
    foo = 10**int(math.log10(min_step))
    sensible_step = int((math.ceil(min_step/foo)) * foo)
    step = sensible_step/tickw
    bar = lambda val: '█'*int(val/step) + ' ▏▎▍▌▋▊▉██'[round((val/step)%1*8)]

    print(fmt.format('#', 'x', (tick_fmt*ticks).format(*((i+1)*sensible_step for i in range(ticks)))))
    for val, count in data:
        tick = ' '*(tickw-1) + '│'
        b = bar(count)
        g = b + '\033[{ct}m'.format(ct=ct) +  (tick*ticks)[len(b):]
        print(fmt.format(val, count, g)[0:cols])


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--ankidir', default='~/Anki')
    parser.add_argument('-p', '--profile')
    parser.add_argument('-d', '--decks', default='0')
    sub = parser.add_subparsers()

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
    def _list_decks(pro, **_):
        list_decks(pro).print_tree()

    @subcmd
    def _print_deck_ids(deck, **_):
        print('\n'.join(deck.ids))

    @subcmd
    def _mature_avg_reviews(args, deck, **_):
        print(deck.mature_avg_reviews(args.cutoff))
    _mature_avg_reviews.parser.add_argument('-c', '--cutoff', default=21)

    @subcmd
    def _revision_histogram(deck, **_):
        pretty_histogram(deck.revision_histogram())

    args = parser.parse_args()
    pros = list_profiles(args.ankidir)
    pro = pros[args.profile] if args.profile else sorted(pros.items())[0][1]
    root = list_decks(pro)
    deck = Deck(root.db, '<query>', None, [ root.child_by_idx(int(idx)) for idx in args.decks.split(',') ])
    args.func(args=args, pro=pro, deck=deck)

