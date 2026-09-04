#!/usr/bin/env python3
"""
Build three synthetic libraries — a SQLite .enl, an EndNote XML export, and a
RIS file — carrying deliberately awkward overlaps drawn from the kinds of
problems a real 30-year humanities library has:

  * the same book in all three libraries, with three different notes
  * subtitle present in one library, absent in another
  * "Nirenberg, David" vs "Nirenberg, D." vs an accented surname
  * a Hebrew-titled record duplicated with and without niqqud
  * two EDITIONS of one book that must NOT be merged
  * a book chapter and its edited volume that must NOT be merged
  * two articles in the same journal issue that must NOT be merged
  * the same article reached by DOI despite a mangled title
"""

from __future__ import annotations

import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

ENL_COLUMNS = [
    "id", "trash_state", "reference_type", "author", "secondary_author",
    "subsidiary_author", "year", "date", "title", "secondary_title",
    "place_published", "publisher", "volume", "number", "pages", "edition",
    "isbn", "doi", "language", "abstract", "notes", "research_notes",
    "keywords", "url", "custom1", "custom2",
]

# reference_type: 6 = Book, 17 = Journal Article, 5 = Book Section
ENL_ROWS = [
    dict(id=1, reference_type=6, author="Nirenberg, David",
         year="1996", title="Communities of Violence",
         place_published="Princeton", publisher="Princeton University Press",
         isbn="0-691-05889-X",
         notes="Read Sept 1998. Chapter 2 on Holy Week riots is the key one.",
         keywords="violence\nIberia\nmedieval",
         custom1="shelf: office A3"),
    dict(id=2, reference_type=6, author="Baer, Yitzhak",
         year="1961", title="A History of the Jews in Christian Spain",
         publisher="Jewish Publication Society", volume="1",
         notes="Vol. 1 only. Translated by Louis Schoffman.",
         subsidiary_author="Schoffman, Louis"),
    dict(id=3, reference_type=17, author="Nirenberg, David",
         year="2002", title="Conversion, Sex, and Segregation",
         secondary_title="American Historical Review", volume="107",
         number="4", pages="1065-1093",
         doi="10.1086/532851",
         notes="Cited in my 2004 piece."),
    dict(id=4, reference_type=6, author="Nirenberg, David",
         year="1996", title="Communities of Violence", edition="1st",
         publisher="Princeton University Press",
         notes="duplicate card, first edition"),
    dict(id=5, reference_type=6, author="בער, יצחק",
         year="1959", title="תּוֹלְדוֹת הַיְּהוּדִים בִּסְפָרַד הַנּוֹצְרִית",
         publisher="מוסד ביאליק", language="Hebrew",
         notes="המהדורה העברית"),
    dict(id=6, reference_type=17, author="Cohen, Jeremy",
         year="1999", title="Living Letters of the Law",
         secondary_title="Speculum", volume="74", number="2", pages="401-425",
         notes="on Augustine's doctrine of Jewish witness"),
    dict(id=7, reference_type=17, author="Cohen, Mark R.",
         year="1999", title="Under Crescent and Cross",
         secondary_title="Speculum", volume="74", number="2", pages="500-522",
         notes="different article, same issue — must stay separate"),
]

XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<xml><records>
{records}
</records></xml>"""

XML_RECORDS = """
<record>
  <rec-number>101</rec-number>
  <ref-type name="Book">6</ref-type>
  <contributors><authors><author><style face="normal">Nirenberg, D.</style></author></authors></contributors>
  <titles><title>Communities of Violence: Persecution of Minorities in the Middle Ages</title></titles>
  <dates><year>1996</year></dates>
  <pub-location>Princeton, NJ</pub-location>
  <publisher>Princeton University Press</publisher>
  <isbn>9780691058894</isbn>
  <notes>Reread 2011 for the seminar. See p. 200 on cross-confessional sex and the logic of coexistence.</notes>
  <research-notes>Compare with Catlos on the "victory of the cross".</research-notes>
  <keywords><keyword>coexistence</keyword><keyword>Iberia</keyword></keywords>
</record>
<record>
  <rec-number>102</rec-number>
  <ref-type name="Book">6</ref-type>
  <contributors><authors><author>Nirenberg, David</author></authors></contributors>
  <titles><title>Communities of Violence: Persecution of Minorities in the Middle Ages</title></titles>
  <dates><year>2015</year></dates>
  <edition>2nd</edition>
  <publisher>Princeton University Press</publisher>
  <notes>Second edition with new preface — page numbers differ from the 1996 printing.</notes>
</record>
<record>
  <rec-number>103</rec-number>
  <ref-type name="Journal Article">17</ref-type>
  <contributors><authors><author>Nirenberg, David</author></authors></contributors>
  <titles><title>Conversion, Sex and Segregation: Jews and Christians in Medieval Spain</title>
    <secondary-title>Am. Hist. Rev.</secondary-title></titles>
  <dates><year>2002</year></dates>
  <volume>107</volume><number>4</number><pages>1065-93</pages>
  <electronic-resource-num>https://doi.org/10.1086/532851</electronic-resource-num>
  <notes>THE article. Use for the conversion chapter.</notes>
</record>
<record>
  <rec-number>104</rec-number>
  <ref-type name="Book Section">5</ref-type>
  <contributors><authors><author>Nirenberg, David</author></authors>
    <secondary-authors><author>Meyerson, Mark D.</author></secondary-authors></contributors>
  <titles><title>Love between Muslim and Jew in Medieval Spain</title>
    <secondary-title>Religion and Minorities in Medieval Iberia</secondary-title></titles>
  <dates><year>2000</year></dates>
  <pages>127-155</pages>
  <notes>chapter in the Meyerson volume</notes>
</record>
<record>
  <rec-number>105</rec-number>
  <ref-type name="Edited Book">28</ref-type>
  <contributors><secondary-authors><author>Meyerson, Mark D.</author></secondary-authors></contributors>
  <titles><title>Religion and Minorities in Medieval Iberia</title></titles>
  <dates><year>2000</year></dates>
  <publisher>Notre Dame</publisher>
  <notes>the volume itself — not the chapter</notes>
</record>
<record>
  <rec-number>106</rec-number>
  <ref-type name="Book">6</ref-type>
  <contributors><authors><author>בער, יצחק</author></authors></contributors>
  <titles><title>תולדות היהודים בספרד הנוצרית</title></titles>
  <dates><year>1959</year></dates>
  <publisher>מוסד ביאליק</publisher>
  <language>Hebrew</language>
  <notes>ללא ניקוד — אותו ספר בדיוק</notes>
</record>
"""

RIS_TEXT = """TY  - BOOK
AU  - Nirenberg, David
TI  - Communities of Violence: Persecution of Minorities in the Middle Ages
PY  - 1996
CY  - Princeton
PB  - Princeton University Press
SN  - 9780691058894
N1  - Current library. Still the best thing on the subject. Cf. Anti-Judaism for the longer arc.
KW  - Iberia
KW  - violence
ER  -

TY  - BOOK
AU  - Baer, Yitzhak
A4  - Schoffman, Louis
TI  - A History of the Jews in Christian Spain
PY  - 1961
PB  - Jewish Publication Society
VL  - 1
N1  - Same as the 1998 card, plus: check vol. 2 for the 1391 material.
ER  -

TY  - JOUR
AU  - Nirenberg, David
TI  - Anti-Judaism and the Western Tradition
T2  - Journal of Modern History
PY  - 2013
VL  - 85
IS  - 3
SP  - 601
EP  - 630
DO  - 10.1086/671154
N1  - unrelated to the 2002 AHR piece
ER  -
"""


def build(root: str) -> None:
    os.makedirs(root, exist_ok=True)

    enl = os.path.join(root, "Nirenberg-1998.enl")
    if os.path.exists(enl):
        os.remove(enl)
    conn = sqlite3.connect(enl)
    conn.execute(f"CREATE TABLE refs ({', '.join(ENL_COLUMNS)})")
    conn.execute("CREATE TABLE file_res (id INTEGER, refs_id INTEGER, file_path TEXT)")
    for row in ENL_ROWS:
        full = {c: row.get(c, "") for c in ENL_COLUMNS}
        full["trash_state"] = 0
        conn.execute(
            f"INSERT INTO refs ({', '.join(ENL_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(ENL_COLUMNS))})",
            [full[c] for c in ENL_COLUMNS])
    conn.execute("INSERT INTO file_res VALUES (1, 1, 'internal-pdf://nirenberg1996.pdf')")
    conn.commit()
    conn.close()

    with open(os.path.join(root, "Nirenberg-2011.xml"), "w", encoding="utf-8") as fh:
        fh.write(XML_TEMPLATE.format(records=XML_RECORDS.strip()))

    with open(os.path.join(root, "Nirenberg-2024.ris"), "w", encoding="utf-8") as fh:
        fh.write(RIS_TEXT)

    print(f"fixture libraries written to {root}")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "fixture-libraries"))
