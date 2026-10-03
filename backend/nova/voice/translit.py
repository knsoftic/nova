"""Roman Urdu -> Urdu script, so the offline Urdu voice (espeak 'ur' phonemes) pronounces replies correctly.

Piper's Urdu voice reads Latin letters with English phonemes ("khul gaya hai" -> "kʌl geɪə haɪ"),
but Urdu script correctly ("کھل گیا ہے" -> "kʰʊl ɡajaː hɛ"). English loanwords (Chrome, Windows,
RAM) are left in Latin script on purpose: the voice pronounces them as English, which is how
they are said in Urdu anyway.

Strategy: a lexicon covering all of NOVA's own reply vocabulary plus common conversational
words; a conservative rule-based fallback only for unknown words that clearly look Roman Urdu.
"""

from __future__ import annotations

import re

LEXICON: dict[str, str] = {
    # pronouns, possessives
    "aap": "آپ", "ap": "آپ", "aapka": "آپ کا", "aapki": "آپ کی", "aapke": "آپ کے", "aapne": "آپ نے",
    "aapko": "آپ کو", "aapse": "آپ سے", "main": "میں", "mein": "میں", "me": "میں", "mera": "میرا",
    "meri": "میری", "mere": "میرے", "mujhe": "مجھے", "mujh": "مجھ", "hum": "ہم", "hamara": "ہمارا",
    "hamari": "ہماری", "hamare": "ہمارے", "humein": "ہمیں", "tum": "تم", "tumhara": "تمہارا",
    "tumhari": "تمہاری", "ye": "یہ", "yeh": "یہ", "wo": "وہ", "woh": "وہ", "is": "اس", "us": "اس",
    "isko": "اس کو", "usko": "اس کو", "ise": "اسے", "isey": "اسے", "unka": "ان کا", "unki": "ان کی",
    "unke": "ان کے", "inka": "ان کا", "apna": "اپنا", "apni": "اپنی", "apne": "اپنے", "khud": "خود",
    "kis": "کس", "kisi": "کسی", "jo": "جو", "jis": "جس", "sab": "سب", "har": "ہر", "dono": "دونوں",
    "koi": "کوئی", "kuch": "کچھ", "kai": "کئی", "ek": "ایک", "aik": "ایک", "si": "سی", "sa": "سا",
    "aa": "آ",
    # particles, conjunctions, adverbs
    "ka": "کا", "ki": "کی", "ke": "کے", "ko": "کو", "se": "سے", "ne": "نے", "par": "پر", "pe": "پہ",
    "tak": "تک", "aur": "اور", "ya": "یا", "lekin": "لیکن", "magar": "مگر", "bhi": "بھی", "hi": "ہی",
    "to": "تو", "kya": "کیا", "kyun": "کیوں", "kyunke": "کیونکہ", "kaise": "کیسے", "kaisi": "کیسی",
    "kaisa": "کیسا", "kaun": "کون", "kaunsa": "کون سا", "kab": "کب", "kahan": "کہاں", "kitna": "کتنا",
    "kitni": "کتنی", "kitne": "کتنے", "jab": "جب", "agar": "اگر", "phir": "پھر", "nahi": "نہیں",
    "nahin": "نہیں", "na": "نہ", "haan": "ہاں", "ji": "جی", "abhi": "ابھی", "ab": "اب", "sirf": "صرف",
    "bohat": "بہت", "bahut": "بہت", "zyada": "زیادہ", "ziada": "زیادہ", "kam": "کم", "thora": "تھوڑا",
    "thori": "تھوڑی", "thore": "تھوڑے", "liye": "لیے", "liya": "لیا", "sath": "ساتھ", "saath": "ساتھ",
    "baad": "بعد", "pehle": "پہلے", "pehli": "پہلی", "pehla": "پہلا", "dafa": "دفعہ", "waqt": "وقت",
    "der": "دیر", "din": "دن", "aaj": "آج", "kal": "کل", "dobara": "دوبارہ", "hamesha": "ہمیشہ",
    "yahan": "یہاں", "wahan": "وہاں", "andar": "اندر", "bahar": "باہر", "upar": "اوپر", "neeche": "نیچے",
    "jaise": "جیسے", "jaisa": "جیسا", "jaisi": "جیسی", "wala": "والا", "wali": "والی", "wale": "والے",
    "zara": "ذرا", "jaldi": "جلدی", "shayad": "شاید", "zaroor": "ضرور", "bilkul": "بالکل", "sahi": "صحیح",
    "theek": "ٹھیک", "thik": "ٹھیک", "galat": "غلط", "ghalat": "غلط", "achha": "اچھا", "acha": "اچھا",
    "achhi": "اچھی", "achhe": "اچھے", "alag": "الگ", "agle": "اگلے", "agla": "اگلا", "agli": "اگلی",
    "naya": "نیا", "nayi": "نئی", "naye": "نئے", "purana": "پرانا", "aham": "اہم", "zaroori": "ضروری",
    "mukammal": "مکمل", "mukhtalif": "مختلف", "khaas": "خاص", "aasan": "آسان", "mushkil": "مشکل",
    "chhota": "چھوٹا", "chhoti": "چھوٹی", "chhote": "چھوٹے", "chota": "چھوٹا", "bara": "بڑا", "bari": "بڑی",
    "bare": "بڑے", "rozana": "روزانہ", "tayyar": "تیار", "maujood": "موجود",
    # be / become / happen
    "hai": "ہے", "hain": "ہیں", "he": "ہے", "ho": "ہو", "hoon": "ہوں", "hun": "ہوں", "tha": "تھا",
    "thi": "تھی", "thin": "تھیں", "hua": "ہوا", "hui": "ہوئی", "hue": "ہوئے", "huay": "ہوئے",
    "hoga": "ہوگا", "hogi": "ہوگی", "honge": "ہوں گے", "hota": "ہوتا", "hoti": "ہوتی", "hote": "ہوتے",
    "gaya": "گیا", "gayi": "گئی", "gaye": "گئے", "gai": "گئی",
    # do / make / give / take
    "kar": "کر", "karo": "کرو", "karna": "کرنا", "karne": "کرنے", "karni": "کرنی", "karte": "کرتے",
    "karta": "کرتا", "karti": "کرتی", "karein": "کریں", "karen": "کریں", "kiya": "کیا", "kiye": "کیے",
    "ki": "کی", "kijiye": "کیجیے", "karwana": "کروانا", "karwaein": "کروائیں", "de": "دے", "do": "دو",
    "diya": "دیا", "di": "دی", "diye": "دیے", "dein": "دیں", "dena": "دینا", "lein": "لیں", "lo": "لو",
    "le": "لے", "lena": "لینا", "bana": "بنا", "banao": "بناؤ", "banana": "بنانا", "banayein": "بنائیں",
    "banaye": "بنائے", "banwana": "بنوانا", "bante": "بنتے", "banta": "بنتا", "banti": "بنتی",
    # continuous / ability / wish
    "raha": "رہا", "rahi": "رہی", "rahe": "رہے", "rahein": "رہیں", "rakhein": "رکھیں", "rakhna": "رکھنا",
    "sakta": "سکتا", "sakti": "سکتی", "sakte": "سکتے", "saka": "سکا", "saki": "سکی", "sakin": "سکیں",
    "saken": "سکیں", "chahiye": "چاہیے", "chahte": "چاہتے", "chahta": "چاہتا", "chahti": "چاہتی",
    # come / go / find / see / tell / ask
    "aayega": "آئے گا", "aayegi": "آئے گی", "aayenge": "آئیں گے", "aaye": "آئے", "aaya": "آیا",
    "aata": "آتا", "aati": "آتی", "aate": "آتے", "jayega": "جائے گا", "jayegi": "جائے گی", "ja": "جا",
    "jata": "جاتا", "jati": "جاتی", "jate": "جاتے", "jaye": "جائے", "mila": "ملا", "mili": "ملی",
    "mile": "ملے", "milega": "ملے گا", "dekh": "دیکھ", "dekho": "دیکھو", "dekhein": "دیکھیں",
    "dikhaya": "دکھایا", "bata": "بتا", "batao": "بتاؤ", "bataiye": "بتائیے", "bataye": "بتائے",
    "bataen": "بتائیں", "batayein": "بتائیں", "bataya": "بتایا", "poochiye": "پوچھیے", "pucho": "پوچھو",
    "samajh": "سمجھ", "samjha": "سمجھا", "samjhi": "سمجھی", "samajhne": "سمجھنے", "samjho": "سمجھو",
    "seekhne": "سیکھنے", "seekhna": "سیکھنا", "suno": "سنو", "sunao": "سناؤ", "bol": "بول", "bolo": "بولو",
    "likh": "لکھ", "likho": "لکھو", "likhein": "لکھیں", "parh": "پڑھ", "parhna": "پڑھنا",
    "chal": "چل", "chalo": "چلو", "chalana": "چلانا", "chalao": "چلاؤ", "kholna": "کھولنا",
    "kholni": "کھولنی", "kholo": "کھولو", "khul": "کھل", "khula": "کھلا", "khuli": "کھلی", "khule": "کھلے",
    "band": "بند", "badalna": "بدلنا", "badal": "بدل", "dhoondna": "ڈھونڈنا", "dhoondo": "ڈھونڈو",
    "maangna": "مانگنا", "pehchanna": "پہچاننا", "rokna": "روکنا", "shuru": "شروع", "khatam": "ختم",
    # nouns
    "kaam": "کام", "cheez": "چیز", "cheezein": "چیزیں", "baat": "بات", "baatein": "باتیں", "sawal": "سوال",
    "sawalon": "سوالوں", "jawab": "جواب", "madad": "مدد", "maloomat": "معلومات", "maloom": "معلوم",
    "masla": "مسئلہ", "masail": "مسائل", "masroof": "مصروف",
    # Multi-PC (Phase 13)
    "beech": "بیچ", "darkhwast": "درخواست", "darkhwastein": "درخواستیں", "haal": "حال", "isi": "اسی", "jor": "جوڑ",
    "jorein": "جوڑیں", "jorna": "جوڑنا", "jorne": "جوڑنے", "jur": "جڑ", "jura": "جڑا", "jure": "جڑے",
    "karwane": "کروانے", "koshishein": "کوششیں", "li": "لی", "mana": "منع", "mumkin": "ممکن", "nizam": "نظام",
    "pate": "پتے", "poochh": "پوچھ", "raabta": "رابطہ", "ruka": "رکا", "sabit": "ثابت","naam": "نام", "alfaaz": "الفاظ", "awaaz": "آواز", "zaban": "زبان",
    "tareeqa": "طریقہ", "wazahat": "وضاحت", "salam": "سلام", "maaf": "معاف", "shukriya": "شکریہ",
    "rabta": "رابطہ", "ghalti": "غلطی", "zindagi": "زندگی", "dost": "دوست", "ghar": "گھر", "dil": "دل",
    "saal": "سال", "ghanta": "گھنٹہ", "ghante": "گھنٹے", "farq": "فرق", "zaiqa": "ذائقہ", "chai": "چائے",
    "pani": "پانی", "khana": "کھانا", "kitab": "کتاب", "duniya": "دنیا", "mulk": "ملک", "shehar": "شہر",
    "patton": "پتوں", "beejon": "بیجوں", "hissa": "حصہ", "tarah": "طرح", "wajah": "وجہ", "ijazat": "اجازت",
    "hifazat": "حفاظت", "khayal": "خیال", "intezar": "انتظار", "koshish": "کوشش", "mazboot": "مضبوط",
    "zarurat": "ضرورت", "faida": "فائدہ", "nuqsan": "نقصان", "tabdeel": "تبدیل", "mehdood": "محدود",
    "mausam": "موسم", "garmi": "گرمی", "sardi": "سردی", "barish": "بارش", "subah": "صبح", "shaam": "شام",
    "raat": "رات", "dopahar": "دوپہر", "hafta": "ہفتہ", "mahina": "مہینہ", "log": "لوگ", "insaan": "انسان",
    "bachche": "بچے", "sehat": "صحت", "aaram": "آرام", "neend": "نیند", "khushi": "خوشی", "pareshan": "پریشان",
    "thaka": "تھکا", "thake": "تھکے", "sawaal": "سوال", "ilm": "علم", "seekh": "سیکھ", "padhai": "پڑھائی",
    "ummeed": "امید", "mubarak": "مبارک", "behtar": "بہتر", "behtareen": "بہترین", "kaafi": "کافی",
    "zaroorat": "ضرورت", "matlab": "مطلب", "yaani": "یعنی", "misaal": "مثال", "maslan": "مثلاً",
    # computer control replies (Phase 6)
    "dabana": "دبانا", "dabaya": "دبایا", "dabao": "دباؤ", "doosre": "دوسرے", "doosra": "دوسرا", "karega": "کرے گا",
    "lana": "لانا", "la": "لا", "nateeja": "نتیجہ", "pooch": "پوچھ", "saamne": "سامنے", "samne": "سامنے",
    "tabdeeli": "تبدیلی", "chhoti": "چھوٹی", "bari": "بڑی", "jagah": "جگہ", "tasdeeq": "تصدیق", "badla": "بدلا",
    "nazar": "نظر", "saaf": "صاف", "tak": "تک", "lein": "لیں", "le": "لے", "shayad": "شاید", "chalane": "چلانے",
    "sakoon": "سکوں", "uski": "اس کی", "use": "اسے", "aayi": "آئی", "dikha": "دکھا", "jise": "جسے",
    "kahein": "کہیں", "khol": "کھول", "lane": "لانے", "likha": "لکھا", "likhne": "لکھنے", "parhne": "پڑھنے",
    # permission questions (Phase 7)
    "aage": "آگے", "ban": "بن", "bhej": "بھیج", "daba": "دبا", "deti": "دیتی", "dhyan": "دھیان", "kaha": "کہا",
    "karoon": "کروں", "karunga": "کروں گا", "khareed": "خرید", "khatarnak": "خطرناک", "lagta": "لگتا",
    "lagti": "لگتی", "likhna": "لکھنا", "mil": "مل", "mita": "مٹا", "poochegi": "پوچھے گی", "poochenge": "پوچھیں گے",
    "rakha": "رکھا", "wapas": "واپس", "yaad": "یاد", "sun": "سن", "mat": "مت", "ruk": "رک", "ruko": "رکو",
    "rehne": "رہنے", "jao": "جاؤ", "han": "ہاں", "haa": "ہاں", "jee": "جی", "kardo": "کر دو", "bhai": "بھائی",
    "nai": "نہیں",
    # browser + research replies (Phase 8A)
    "aakhir": "آخر", "aisi": "ایسی", "baare": "بارے", "banayi": "بنائی", "bharosemand": "بھروسہ مند",
    "daalein": "ڈالیں", "dhoond": "ڈھونڈ", "faislon": "فیصلوں", "jiski": "جس کی", "kabhi": "کبھی", "khaali": "خالی",
    "khabron": "خبروں", "khabrein": "خبریں", "khane": "خانے", "kholega": "کھولے گا", "kholein": "کھولیں",
    "khulasa": "خلاصہ", "lagega": "لگے گا", "layak": "لائق", "likhta": "لکھتا", "mojood": "موجود", "pichla": "پچھلا",
    "agla": "اگلا", "pohncha": "پہنچا", "poori": "پوری", "taza": "تازہ", "wahi": "وہی", "wazeh": "واضح",
    "kami": "کمی", "ikhtilaf": "اختلاف",
    # Phase 8B: files and code
    "aakhri": "آخری", "adhoora": "ادھورا", "adhoori": "ادھوری", "aise": "ایسے", "badalne": "بدلنے", "badalni": "بدلنی",
    "badalta": "بدلتا", "badli": "بدلی", "banata": "بناتا", "banaya": "بنایا", "baqi": "باقی", "bheja": "بھیجا",
    "bhejna": "بھیجنا", "bina": "بنا", "bunyadi": "بنیادی", "chala": "چلا", "chalata": "چلاتا", "chalenge": "چلیں گے",
    "chalta": "چلتا", "chalti": "چلتی", "chuki": "چکی", "chunein": "چنیں", "dabayein": "دبائیں", "dene": "دینے",
    "dhoondein": "ڈھونڈیں", "dikhai": "دکھائی", "dikhao": "دکھاؤ", "foran": "فوراً", "gayin": "گئیں", "hal": "حل",
    "hata": "ہٹا", "hataya": "ہٹایا", "hil": "ہل", "hilane": "ہلانے", "hilengi": "ہلیں گی", "hisaab": "حساب",
    "hongi": "ہوں گی", "isay": "اسے", "istemal": "استعمال", "jaiza": "جائزہ", "jana": "جانا", "jayengi": "جائیں گی",
    "karke": "کر کے", "kharab": "خراب", "kholne": "کھولنے", "kholta": "کھولتا", "laane": "لانے", "laata": "لاتا",
    "likhi": "لکھی", "milegi": "ملے گی", "milte": "ملتے", "milti": "ملتی", "mit": "مٹ", "nishan": "نشان",
    "parhi": "پڑھی", "parhta": "پڑھتا", "parta": "پڑتا", "pehchana": "پہچانا", "pichli": "پچھلی", "poora": "پورا",
    "purani": "پرانی", "qism": "قسم", "rakh": "رکھ", "rok": "روک", "samjhana": "سمجھانا", "samjhao": "سمجھاؤ",
    "soch": "سوچ", "tajweez": "تجویز", "tarteeb": "ترتیب", "tasveer": "تصویر", "toot": "ٹوٹ", "un": "ان",
    "uska": "اس کا", "uske": "اس کے", "cheezein": "چیزیں", "batata": "بتاتا", "bhejta": "بھیجتا", "deta": "دیتا",
    "dhoondta": "ڈھونڈتا", "khatre": "خطرے", "leta": "لیتا", "julte": "جلتے",
    # Phase 8C: settings, messages, design
    "badlaav": "بدلاؤ", "badlo": "بدلو", "bhejne": "بھیجنے", "chahein": "چاہیں", "chalu": "چالو", "chun": "چن",
    "dabayenge": "دبائیں گے", "dekhna": "دیکھنا", "dikhana": "دکھانا", "ghumao": "گھماؤ", "haroof": "حروف",
    "hatana": "ہٹانا", "hona": "ہونا", "jayenge": "جائیں گے", "khulne": "کھلنے", "lag": "لگ", "lamba": "لمبا",
    "paas": "پاس", "pakka": "پکا", "rang": "رنگ", "waisi": "ویسی", "yahi": "یہی",
    # Phase 9: memory, history, workflows
    "baaton": "باتوں", "bas": "بس", "bhool": "بھول", "cheezon": "چیزوں", "chhor": "چھوڑ", "chhorna": "چھوڑنا",
    "daal": "ڈال", "dilana": "دلانا", "dunga": "دوں گا", "inhein": "انہیں", "jaoon": "جاؤں", "kahunga": "کہوں گا",
    "keh": "کہہ", "kehne": "کہنے", "kholoon": "کھولوں", "lambi": "لمبی", "lunga": "لوں گا", "maine": "میں نے",
    "mitai": "مٹائی", "mitana": "مٹانا", "mitane": "مٹانے", "parega": "پڑے گا", "pichle": "پچھلے", "rahegi": "رہے گی",
    "rakhi": "رکھی", "rakhni": "رکھنی", "rakho": "رکھو", "rakhoon": "رکھوں", "rakhta": "رکھتا", "saari": "ساری",
    "sire": "سرے", "tasveerein": "تصویریں", "yaadein": "یادیں",
    # Phase 10: behavior layer
    "aadat": "عادت", "aadatein": "عادتیں", "aam": "عام", "aayengi": "آئیں گی", "aksar": "اکثر", "andaz": "انداز",
    "andaza": "اندازہ", "bole": "بولے", "dekha": "دیکھا", "dheere": "دھیرے", "doon": "دوں", "doonga": "دوں گا",
    "halat": "حالت", "halki": "ہلکی", "kahi": "کہی", "kholte": "کھولتے", "lagte": "لگتے", "mitengi": "مٹیں گی",
    "mutabiq": "مطابق", "naraazgi": "ناراضگی", "oonchi": "اونچی", "pur": "پر", "seedha": "سیدھا",
    "seekhega": "سیکھے گا", "sukoon": "سکون", "tafseel": "تفصیل", "tar": "تر", "tez": "تیز", "thakan": "تھکن",
    "uljhan": "الجھن", "zor": "زور",
    # Phase 11: admin, tests, bugs
    "bani": "بنی", "chhup": "چھپ", "chhupaya": "چھپایا", "chhupaye": "چھپائے", "ijazatein": "اجازتیں",
    "likhe": "لکھے", "masle": "مسئلے", "nakaam": "ناکام", "parha": "پڑھا", "pasand": "پسند", "pehchan": "پہچان",
    "poochi": "پوچھی", "qaide": "قاعدے", "samajhta": "سمجھتا",
}
# "ki" appears twice above (possessive and "did"); both are written the same in Urdu.

PHRASES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bassalam[\s-]*o[\s-]*alaikum\b", re.IGNORECASE), "السلام علیکم"),
    (re.compile(r"\bwa[\s-]*alaikum[\s-]*(?:us[\s-]*)?salam\b", re.IGNORECASE), "وعلیکم السلام"),
    (re.compile(r"\bin[\s-]*sha[\s-]*allah\b", re.IGNORECASE), "ان شاء اللہ"),
    (re.compile(r"\bjazak[\s-]*allah\b", re.IGNORECASE), "جزاک اللہ"),
]

# Endings that are clearly Roman Urdu verb/noun forms; used to decide the fallback is safe.
URDU_ENDINGS = re.compile(r"(?:ein|iye|aiye|ega|egi|enge|ayein|aate|aati|wana|wani|wane|ogi|oge|unga|ungi)$")

DIGRAPHS = [("kh", "خ"), ("gh", "غ"), ("sh", "ش"), ("ch", "چ"), ("th", "تھ"), ("ph", "پھ"), ("bh", "بھ"),
            ("dh", "دھ"), ("jh", "جھ"), ("zh", "ژ")]
CONSONANTS = {"b": "ب", "p": "پ", "t": "ت", "d": "د", "r": "ر", "z": "ز", "s": "س", "f": "ف", "q": "ق",
              "k": "ک", "g": "گ", "l": "ل", "m": "م", "n": "ن", "w": "و", "v": "و", "h": "ہ", "y": "ی",
              "j": "ج", "x": "کس", "c": "ک"}

WORD = re.compile(r"[A-Za-z']+")


def _fallback(word: str) -> str:
    """Rough letter-by-letter transliteration for unknown words that look Roman Urdu."""
    w = word.lower().replace("'", "")
    out: list[str] = []
    i = 0
    while i < len(w):
        pair = w[i:i + 2]
        first, last = i == 0, i == len(w) - 1
        if pair in ("aa",):
            out.append("آ" if first else "ا"); i += 2; continue
        if pair in ("ee", "ii"):
            out.append("ای" if first else "ی"); i += 2; continue
        if pair in ("oo", "uu"):
            out.append("او" if first else "و"); i += 2; continue
        if pair == "ai":
            out.append("ای" if first else ("ے" if i + 2 == len(w) else "ی")); i += 2; continue
        if mapped := dict(DIGRAPHS).get(pair):
            out.append(mapped); i += 2; continue
        ch = w[i]
        if ch == "a":
            out.append("ا" if first or last else "")
        elif ch in "iu":
            out.append("ا" if first else ("ی" if ch == "i" and last else ""))
        elif ch == "e":
            out.append("ا" if first else ("ے" if last else "ی"))
        elif ch == "o":
            out.append("او" if first else "و")
        else:
            out.append(CONSONANTS.get(ch, ""))
        i += 1
    if out and w.endswith("n") and len(w) > 2 and w[-2] in "aeiou":
        out[-1] = "ں"  # nasal ending: "karein" style
    return "".join(out)


def _convert_word(word: str) -> str:
    lower = word.lower()
    if lower in LEXICON:
        return LEXICON[lower]
    if word.isupper() and len(word) > 1:
        return word  # acronym: RAM, CPU, GB are read as English letters
    if URDU_ENDINGS.search(lower):
        return _fallback(word)
    return word  # most likely an English word or a name: keep it, the voice reads it as English


def to_urdu_script(text: str) -> str:
    for pattern, urdu in PHRASES:
        text = pattern.sub(urdu, text)
    return WORD.sub(lambda m: _convert_word(m.group(0)), text)


def prepare_for_speech(text: str) -> str:
    """Clean a display reply for the voice: drop symbols the voice would read out, then convert."""
    text = re.sub(r"\s*\(([^)]*)\)", r"، \1،", text)  # parentheses -> pauses
    text = re.sub(r"\s+/\s+", " میں سے ", text)  # "21 GB free / 237 GB"
    text = re.sub(r"[•·→—–_*#\"“”]", " ", text)
    text = re.sub(r"(\d)\s*%", r"\1 فیصد", text)
    text = re.sub(r"^\s*(\d+)\.\s", r"\1، ", text, flags=re.MULTILINE)  # numbered lists
    text = re.sub(r"\s*\n+\s*", "۔ ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return to_urdu_script(text)
