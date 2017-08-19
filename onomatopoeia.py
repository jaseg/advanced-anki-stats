# coding: utf-8

import words # jmdict
import stats # for pretty_histogram
import collections

words.mapping['ぶるぶる']

len([e for e in words.entries if any(words.EntryType('on_mim') in t.misc for t in e.translations)])

kana = list('あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわがぎぐげござじずぜぞだでどばびぶべぼぱぴぷぺぽ')
kana_comp = [a+b for a in 'きしちにひみりぎじび' for b in 'ゃゅょ']
all_kana = kana + kana_comp

dakuon_map = dict(zip('がぎぐげござじずぜぞだでどばびぶべぼぱぴぷぺぽ', 'かきくけこさしすせそたてとはひふへほはひっふへほ'))
undakuon = lambda k: dakuon_map.get(k, k)
u = undakuon

comb = [ a+b+a+b for a in all_kana for b in all_kana]
print('Percentage of four-kana abab combinations present in dictionary including 拗音',
        len(set(comb) & words.mapping.keys())/len(comb)*100)

comb_red = [ a+b+a+b for a in kana[5:] for b in kana[5:]]
print('Percentage of four-kana abab combinations present in dictionary excluding 拗音 and あいうえお',
        len(set(comb_red) & words.mapping.keys())/len(comb_red)*100)

comb_red2 = [ a+b+a+b for a in kana for b in kana]
print('Percentage of four-kana abab combinations present in dictionary excluding 拗音',
        len(set(comb_red2) & words.mapping.keys())/len(comb_red2)*100)

print('Number of four-kana abab combinations present in dictionary excluding 拗音 ignoring 濁点 and 半濁点',
        len({ a+b+c+d for a,b,c,d in (w for w in words.mapping.keys() if len(w) == 4) if u(a) == u(c) and u(b) == u(d) }))
s = { a+b+c+d for a,b,c,d in (w for w in words.mapping.keys() if len(w) == 4) if u(a) == u(c) and u(b) == u(d) and a in kana and b in kana }

print('Histogram of most common kana in four-kana abab combinations ignoring 濁点 and 半濁点')
print(stats.pretty_histogram(collections.Counter([a+'\u200b' for a,b,c,d in s] + [b+'\u200b' for a,b,c,d in s]).most_common()))

combl = lambda coll: [ a+b+a+b for a in coll for b in coll]
topn = lambda n: combl([a for a,_b in collections.Counter([a for a,b,c,d in s] + [b for a,b,c,d in s]).most_common(n)])
perc = lambda st: len(set(st) & words.mapping.keys())/len(st)*100

print('Percentage of four-kana abab combinations from top 5 kana in the dictionary ignoring 濁点 and 半濁点',
        perc(topn(5)))
print('Percentage of four-kana abab combinations from top 10 kana in the dictionary ignoring 濁点 and 半濁点',
        perc(topn(10)))
print('Percentage of four-kana abab combinations from kana in the dictionary ignoring 濁点 and 半濁点',
        perc(topn(None)))

print('Histogram of the above')
print(stats.pretty_histogram([ (i, perc(topn(i))) for i in range(1,len(kana)+1) ] , cfmt='{:2.5f}'))
