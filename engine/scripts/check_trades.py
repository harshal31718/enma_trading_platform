import json

p2 = json.load(open('scripts/golden/phase2_corrected.json'))
p3 = json.load(open('scripts/golden/phase3.json'))

m2 = p2['results']['MicroScalper']
m3 = p3['results']['MicroScalper']

print("MicroScalper:")
print("  P2 netProfit:", m2.get('netProfit'))
print("  P3 netProfit:", m3.get('netProfit'))
print("  P2 cagrPct:", m2.get('cagrPct'))
print("  P3 cagrPct:", m3.get('cagrPct'))
print("  P2 finishingBalance:", m2.get('finishingBalance'))
print("  P3 finishingBalance:", m3.get('finishingBalance'))
