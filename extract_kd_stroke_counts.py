#!/usr/bin/env python3
# coding: utf-8
import sys
import re
import json
import itertools
import argparse

import bs4

import stats

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-k', '--kanjilist-out', type=argparse.FileType('w'))
    parser.add_argument('-c', '--strokecount-out', type=argparse.FileType('w'))
    parser.add_argument('collection')
    args = parser.parse_args()

    root = stats.list_decks(args.collection)
    deck, = ( d for d in root.subdecks if 'kanji' in d.name.lower() and 'damage' in d.name.lower() )

    models = json.loads(deck.db.execute('SELECT models FROM col').fetchone()[0])
    fieldnames = {
            int(model_id): [
                field['name']
                for field in model['flds']
            ] for model_id, model in models.items()
        }
    (model,), = models = deck._iexec('SELECT DISTINCT mid FROM cards JOIN notes ON cards.nid=notes.id WHERE cards.did IN ({ids})').fetchall()
    names = fieldnames[model]

    cards = deck._iexec('SELECT DISTINCT mid,flds FROM cards JOIN notes ON cards.nid=notes.id WHERE cards.did IN ({ids})').fetchall()
    cards_mapped = [ dict(zip(fieldnames[model_id], fields.split('\x1f'))) for model_id, fields in cards ]

    headers = [ bs4.BeautifulSoup(card['Full header'], 'lxml') for card in cards_mapped ]
    stroke_counts = { kanji: int(strokes.strip().split()[0]) if strokes else None for kanji, strokes in ((header.find(class_='kanji_character').text, header.find(text=re.compile('strokes'))) for header in headers) }

    n_cards = len(cards)
    print('Number of cards found:', n_cards)
    n_kanji = len([ k for k in stroke_counts.keys() if len(k) == 1])
    print('Number of kanji found:', n_kanji, 'delta', n_kanji-n_cards)

    if args.kanjilist_out:
        for k in sorted(stroke_counts.keys()):
            if len(k) == 1:
                print(k, file=args.kanjilist_out)
                
    n_sc = len([ k for k, c in stroke_counts.items() if len(k) == 1 and c ])
    print('Number of kanji with stroke counts:', n_sc, 'delta', n_sc-n_cards)

    if args.strokecount_out:
        for k, c in sorted(stroke_counts.items(), key=lambda x: x[0]):
            if len(k) == 1 and c:
                print(k, c, file=args.strokecount_out)
    
    sorted_counts = sorted(val for val in stroke_counts.values() if val is not None)
    hist_data = [ (v, len(list(group))) for v, group in itertools.groupby(sorted_counts) ]
    print(stats.pretty_histogram(hist_data))

