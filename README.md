# ⚔️ Totally Accurate Battle Simulator

Un simulator de lupta 3D low-poly, facut in Python cu [Ursina](https://www.ursinaengine.org/).

Plasam doua armate fata in fata, apasam **SPACE** si ne uitam cum se lupta. Odata pornita lupta, nu mai controlam nimic: fiecare unitate isi cauta singura cel mai apropiat inamic, se apropie, ocoleste copacii si pietrele, tinteste si trage.

<br>

## 🎯 Ce gasim in joc

- **5 tipuri de unitati**, fiecare cu rolul ei: soldat, lunetist, RPG, mitralior si tanc.
- **Un camp de lupta adevarat**, cu dealuri, un rau, un drum de pamant, copaci si bolovani, inconjurat de munti.
- **Proiectile pe care le vedem zburand**: gloante trasoare, rachete si obuze.
- **Explozii** care lovesc tot ce e in jur si arunca unitatile in spate.
- **Blindaj**: tancurile abia simt gloantele, dar rachetele le doboara repede.
- **Animatii** pentru mers, reculul armei, reincarcare si turela de tanc care sare in aer cand tancul e distrus.
- **Optimizat** pentru un numar mare de unitati.

<br>

## 🚀 Pornire

Avem nevoie de **Python 3.9+** si de **Ursina**:

```bash
git clone https://github.com/<utilizator>/<repo>.git
cd <repo>
pip install ursina
python tabs_3d_varianta_4.py
```

<br>

## 🎮 Controale

1. **Alegem o unitate** cu tastele `1`–`5`. Unitatea selectata apare sus pe ecran.
2. **Alegem echipa** cu `T`. Cercul de sub cursor se coloreaza in rosu sau albastru.
3. **Dam click pe teren** ca sa punem unitatea. Daca tinem click-ul apasat si miscam mouse-ul, putem plasa un rand intreg de unitati, distantate automat.
4. **`Z`** sterge ultima unitate pusa, daca am gresit. Putem apasa de mai multe ori.
5. **`SPACE`** porneste lupta. Avem nevoie de cel putin o unitate in fiecare echipa.
6. **`R`** goleste arena, ca s-o putem lua de la capat.

| Ce vrem sa facem | Cum |
|---|---|
| Rotim camera | click dreapta + mouse |
| Facem zoom | scroll |
| Mutam camera | click pe rotita + mouse |

<br>

## 🪖 Unitatile

| Tasta | Unitate | Viata | Raza | Damage | Pe scurt |
|:---:|---|:---:|:---:|:---:|---|
| `1` | **Soldat** | 100 | 11 | 14 | Bun la toate, nu exceleaza la nimic. |
| `2` | **Lunetist** | 70 | 30 | 80 | Loveste de departe, dar trage rar. |
| `3` | **RPG** | 90 | 14 | 65 + zona | Vanatorul de tancuri. |
| `4` | **Mitralior** | 150 | 12 | 7 | Ploaie de gloante, putina precizie. |
| `5` | **Tanc** | 900 | 18 | 110 + zona | Greu de oprit, se intoarce incet. |

**Soldatul** este structura de baza a oricarei armate. Are o pusca de asalt cu 12 gloante in incarcator si se descurca in orice situatie.

**Lunetistul** are o raza de actiune aproape cat toata arena si omoara un soldat din doua focuri. In schimb, trage o data la trei secunde, are putina viata si nimereste foarte greu prin luneta daca inamicul ajunge langa el.

**RPG-ul** lanseaza o racheta lenta care explodeaza la impact. Contra tancurilor face **de 3 ori mai mult damage**. Dupa fiecare racheta are nevoie de cateva secunde ca sa reincarce.

**Mitraliorul** trage aproape continuu, cu 40 de gloante pe incarcator, dar imprastie mult. Are cea mai multa viata dintre trupele de infanterie si este greu de impins. Perfect ca sa opreasca un val de infanterie, inutil contra tancurilor.

**Tancul** are 900 HP si blindaj: gloantele de pusca ii fac doar o treime din damage. Obuzul lui exploziv are un efect distructiv imens, iar soldatii din calea lui sunt impinsi deoparte. Cand este distrus, explodeaza, turela zboara in aer, iar epava fumega cateva secunde.

<br>

## 💡 Ce trebuie sa stim inainte de prima batalie

- **Tancurile se opresc cu RPG-uri.** Gloantele au un efect redus asupra lor.
- **Raul incetineste.** Prin apa unitatile merg aproape la jumatate de viteza.
- **Distanta conteaza.** Toate unitatile nimeresc mai greu de departe, mai putin lunetistul, care ramane precis.
- **Copacii si pietrele din arena sunt obstacole reale.** Unitatile le ocolesc, dar asta le poate intarzia.
- **Barele de viata** apar abia dupa prima lovitura, ca sa nu incarce ecranul.

<br>

## 🔊 Sunet

Jocul merge perfect si fara sunet. Daca vrem sunet, punem langa script fisierele de mai jos:

| Fisier | Pentru |
|---|---|
| `pusca.wav` | soldat |
| `sniper.wav` | lunetist |
| `rpg.wav` | lansare racheta |
| `mitraliera.wav` | mitralior |
| `tun.wav` | tanc |
| `explozie.wav` | explozii |
| `muzica.mp3` | muzica de fundal in timpul luptei |

<br>

## 🛠️ Modificari

Aproape totul se regleaza din valorile de la inceputul fisierului si din `STATS`-ul fiecarei clase de unitate (`Rifleman`, `Sniper`, `RocketSoldier`, `MachineGunner`, `Tank`). Cateva exemple:

| Valoare | Ce seteaza |
|---|---|
| `ARENA_HALF` | cat de mare este arena |
| `WATER_SLOWDOWN` | cat de tare incetineste apa |
| `PROJECTILES` | viteza proiectilelor si eficienta lor contra blindajului |
| `TEAM_COLORS` | culorile echipelor |

Ca sa adaugam o unitate noua:

1. Facem o clasa care mosteneste `Unit` si ii dam statistici.
2. Ii construim modelul in `infantry_models()`.
3. O adaugam in `UNIT_TYPES` pe o tasta libera, de exemplu `6`.

<br>

## ❓ Probleme frecvente

**Jocul nu porneste si apare `No module named 'ursina'`.**
Rulam `pip install ursina` cu acelasi Python cu care pornim jocul.

**Nu putem pune unitati.**
Cursorul trebuie sa fie pe zona de lupta, nu pe munti. Daca lupta a inceput deja, apasam `R`.

**Jocul merge greu.**
Scadem `MAX_EFFECTS` sau folosim mai putine tancuri si RPG-uri, pentru ca exploziile produc cel mai mult fum.
