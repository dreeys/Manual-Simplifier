# Manual Simplifier

Upload a product manual (PDF) and get back a short guide with only the steps that matter. No warranty pages, no parts lists — just how to set it up.

![Upload screen](screenshots/upload.png)
![Guide output](screenshots/guide.png)

Built this as a fun side project with Claude as my coding assistant. The idea came from being annoyed at how long most product manuals are when all you want to know is how to get started.

## How it works

The PDF text is extracted with PyMuPDF and sent to Llama 3.1 (via Groq) with a prompt that tells it to pull out the 4–5 most important setup steps and ignore everything else. The result comes back as JSON and gets saved in a local SQLite database so you can look up previous guides.

## Stack

- **Backend** — Python, Flask
- **AI** — Groq API (Llama 3.1 8B)
- **PDF parsing** — PyMuPDF
- **Storage** — SQLite
- **Frontend** — Vanilla JS, HTML/CSS

## Run it

You'll need a free [Groq API key](https://console.groq.com).

```bash
git clone https://github.com/dreeys/manual-simplifier.git
cd manual-simplifier
pip install -r requirements.txt
echo "GROQ_API_KEY=your_key_here" > .env
python app.py
```

Then open [http://localhost:5001](http://localhost:5001).
