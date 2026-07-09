# 🏥 Medical Chatbot — Project Notes (Hinglish)

> Yeh file mera pura project samajhne ke liye hai. Koi bhi poochhe — teacher, interviewer, mentor —
> toh yahan se padh ke confidently bata sakti hoon.

---

## 1. Project hai kya? (One line)
Ek **AI medical assistant website** hai jahan patient login karke health ke sawaal pooch sakta hai,
appointment book kar sakta hai, apni reports/prescriptions dekh sakta hai — aur ek **hidden admin panel**
hai jahan se doctor/staff sab manage karta hai. Poora **24/7 online (Railway pe live)** chalta hai.

**Live links:**
- Patient portal: https://medical-chatbot-production-e9fc.up.railway.app
- Admin (hidden): https://medical-chatbot-production-e9fc.up.railway.app/admin-login

---

## 2. Sabse important concept — RAG
Chatbot normal ChatGPT jaisa nahi hai. Yeh **RAG** use karta hai — *Retrieval Augmented Generation*.

**Simple bhasha mein:** "AI ko sirf apne dimaag se jawab nahi dene dete. Pehle hamari medical
documents mein se relevant part dhoondte hain, phir woh part AI ko dete hain aur bolte hain —
'is info ke hisaab se jawab do'."

**2 fayde:** (1) jawab hamare data pe based, galat/bana-hua kam. (2) apni marzi ke documents daal sakte hain.

---

## 3. Kaun sa AI (do alag AI use kiye)
| Kaam                                              | AI                         |
|---------------------------------------------------|----------------------------|
| Chat ke jawab (patient se baat)                   | Google Gemini (gemini-2.5-flash) |
| Medical tools (lab report, symptom, drug-check…)  | Claude (claude-haiku)      |

Khaas baat: jis bhasha mein sawaal aaye usi mein jawab (Hindi/Hinglish/English).

---

## 4. Tech Stack (kaunsi cheez kis kaam ki)

**Backend (Python):**
- FastAPI — website ka server (saari requests handle)
- Uvicorn — server chalane wala engine
- ChromaDB — vector database (embeddings store)
- sentence-transformers (all-MiniLM-L6-v2) — text ko numbers/embeddings mein badalta
- google-generativeai — Gemini se baat
- anthropic — Claude se baat
- pypdf — PDF padhne ke liye
- SQLite — normal data (patients, appointments, bills) data/ folder mein
- PyJWT + passlib — login security (token + encrypted password)

**Frontend:** Plain HTML + CSS + JavaScript (static/ folder — portal.html, chat.html, admin.html …)

**Deployment:** Docker (app ko box mein pack) + GitHub (code store) + Railway (24/7 cloud).

---

## 5. Poora Flow: sawaal se jawab tak (A → Z)

Example sawaal: *"Sugar zyada ho to kya khana chahiye?"*

- **STEP 0 — Login:** email+password → token browser mein save (entry pass).
- **STEP 1 — Sawaal server tak:** chat.html JS sawaal ko /chat endpoint pe bhejta (+ purani history).
- **STEP 2 — Embedding:** sawaal ko all-MiniLM-L6-v2 numbers ki list (vector) mein badalta.
- **STEP 3 — Retrieval:** ChromaDB se top-5 sabse milte-julte chunks nikaalta. (= "R")
- **STEP 4 — Augmented:** chunks + sawaal + System Prompt (rules) ka package banta. (= "A")
- **STEP 5 — Generation:** Google Gemini yeh padh ke simple jawab banata. (= "G")
- **STEP 6 — Jawab wapas:** screen pe chat bubble mein dikh jaata. Total 2-3 second.

```
Patient sawaal
   -> Login token check
   -> Sawaal to NUMBER (embedding)
   -> ChromaDB se top-5 chunks (Retrieval)
   -> Chunks + Sawaal + Rules (Augmented)
   -> Google Gemini (Generation)
   -> Simple jawab -> Patient screen
```

---

## 6. Features

**Patient side:**
- Email+password login (30 din, kisi bhi device se)
- AI chatbot se health sawaal
- Appointment booking (12 doctors, date+time slot)
- Prescriptions, lab reports, bills, treatment plans dekhna
- Forgot password (email reset link)
- Booking hote hi email confirmation (naya)

**Admin side (hidden /admin-login):**
- Patients, appointments, bills, prescriptions manage
- AI tools: lab report analysis, symptom checker, drug-interaction, health risk score, weekly report
- Knowledge Base panel: naya document upload -> chatbot turant smart
- Audit log: admin ne kya kiya sab record (security)
- First-admin rule: ek admin ban gaya to public signup band

---

## 7. Banane ka safar (Step by step)
1. Medical documents data/ folder mein daale.
2. ingest.py chalaya -> chunks + embeddings + ChromaDB mein store ("chatbot ki padhai").
3. rag.py banaya -> sawaal par relevant chunks nikaal ke Gemini se jawab.
4. FastAPI backend (app/main.py) -> saare pages/buttons ke endpoints.
5. HTML pages (static/) -> patient aur admin screens.
6. Login/security -> JWT + encrypted passwords.
7. Extra modules -> appointments, billing, lab reports, notifications, AI tools (har ek alag .py).
8. Docker mein pack (Dockerfile, CPU-only PyTorch).
9. GitHub pe daala.
10. Railway pe deploy -> env vars (API keys) set -> live 24/7.

---

## 8. Ek line mein pura project
"Yeh Python (FastAPI) se bana AI medical assistant hai jo RAG technique use karta hai — medical
documents ko ChromaDB vector database mein store karta hai, patient ke sawaal par relevant info
nikaal ke Google Gemini se jawab deta hai. Medical tools ke liye Claude AI. Frontend HTML/JS,
aur pura Docker se Railway cloud pe 24/7 live."

---

## 9. Yaad rakhne wali 3 khaas baatein
1. AI apne mann se nahi, hamare documents se jawab deta -> hallucination kam.
2. Naya document upload -> chatbot turant smart (dobara "train" nahi karna padta).
3. Do database: ChromaDB (AI/meaning ke liye) + SQLite (normal data ke liye).

---

## 10. Common technical words (short meaning)
- **RAG** = Retrieval Augmented Generation (documents dhoond ke AI se jawab)
- **Embedding** = text ka meaning numbers mein
- **Vector Database (ChromaDB)** = meaning-wale numbers store + search
- **Chunk** = document ka chhota tukda
- **API key** = AI service (Gemini/Claude) use karne ki secret chaabi
- **Endpoint** = server ka ek address (jaise /chat, /api/book)
- **JWT token** = login ke baad mila "entry pass"
- **Docker** = app ko ek box mein pack karna taaki kahin bhi same chale
- **Deploy** = app ko internet pe live karna
