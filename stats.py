#!/usr/bin/env python3

import sqlite3
import shutil
from os import path
from contextlib import contextmanager
import json
from itertools import groupby

@contextmanager
def dbopen(dbdir, dbfile):
    try:
        db = sqlite3.connect(path.expanduser(path.join(dbdir, dbfile)))
        yield db
    finally:
        db.close()

def list_profiles(anki_dir='~/Anki'):
    with dbopen(anki_dir, 'prefs.db') as db:
        return [ (name, path.join(anki_dir, name))
                for name, in db.execute('SELECT name FROM profiles WHERE name != "_global"').fetchall() ]

def list_decks(profile_dir='~/Anki/User 1'):
    with dbopen(profile_dir, 'collection.anki2') as db:
        if db.execute('SELECT COUNT(*) FROM col').fetchone() > (1,):
            raise UserWarning('Profile contains more than one collection.')
        decks = json.loads(db.execute('SELECT decks FROM col LIMIT 1').fetchone()[0])

        # NOTE: The deck_id check for the special "Default" deck is a bit heuristic here. This deck is created when the
        # profile is initialized and as such AFAICT will always end up with the sqlite ID 1. We can't reliably use the
        # deck name, as that one is just "Default", and nothing prevents anyone from naming a regular deck thus. This
        # sqlite ID hack is also what Anki itself uses.

        res = [ (['<everything>'] + data['name'].split('::'), deck_id)
                for deck_id, data
                in decks.items()
                if deck_id != '1'
            ]
#        if len(res) != len(decks):
#            raise UserWarning('Profile contains duplicate deck name.')

        build_decks = lambda res: [
                Deck(db,
                     key,
                     list(group)[0][1], # the group's first element is the one with the shortest name, i.e. the super-deck
                     build_decks( ( (n[1:],did) for n,did in group[1:] ) )
                )
                for key,group
                in (
                    (key, list(group))
                    for key,group
                    in groupby(
                        sorted(res),
                        lambda el: el[0][0]
                    )
                )
            ]

#        res = [ Deck(db, name, deck_id) for name,deck_id in sorted(res) if deck_id != '1' ]

        return build_decks(res)[0]
#        return { name: Deck(db,
#                            name,
#                            deck_id,
#                            { iid for iname,iid in res.items() if iname.startswith(name+'::') )
#                for name, deck_id in res.items() }

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
        self.ids = {own_id}
        for d in subdecks:
            self.ids |= d.ids

    def mature_avg_reviews(self, cutoff_interval: 'days'=21):
        with self.db as db:
            return db.execute('SELECT AVG(cnt) FROM ('
                    'SELECT COUNT(*) as cnt FROM revlog JOIN cards ON cid=cards.id '
                    'WHERE did IN ? AND cards.ivl > ? GROUP BY cid)', self.ids, cutoff_interval).fetchone()[0]

    def revision_histogram(deck):
        with self.db as db:
            return db.execute('SELECT cnt, COUNT(*) FROM ('
                    'SELECT COUNT(*) AS cnt FROM revlog JOIN cards ON cid=cards.id '
                    'WHERE did IN ? GROUP BY cid'
                ') GROUP BY cnt', self.ids).fetchall()

if __name__ == '__main__':
    pros = list_profiles()
    from pprint import pprint
    pprint(pros)
    root = list_decks(pros[0][1])
    root.print_tree()
    print(0, root.child_by_idx(0).name)
    print(1, root.child_by_idx(1).name)
    print(2, root.child_by_idx(2).name)
    print(5, root.child_by_idx(5).name)
    print(10, root.child_by_idx(10).name)
    print(17, root.child_by_idx(17).name)

