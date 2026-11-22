Echosent

A web-based evaluation system that uses multilingual BERT (mBERT) to analyze the sentiment of anonymous student feedback on faculty, staff, facilities, and payments.

Echosent was developed as a research project. Students submit anonymous evaluations across several categories (faculty, staff, facilities, and payments), and the system automatically classifies the written comments by sentiment so that administrators and faculty can understand feedback at a glance.

🌐 Live site: https://your-domain.com

Table of Contents
About
Key Features
User Roles
How It Works
Sentiment Analysis Model
Tech Stack
Getting Started
Project Structure
Configuration
Privacy and Anonymity
Roadmap
Research Team
License
About

Traditional evaluations produce large amounts of written feedback that is time-consuming to read and summarize. Echosent addresses this by combining an anonymous evaluation form with an automated sentiment analysis pipeline powered by mBERT (Multilingual BERT).

The system lets students give honest feedback without fear of being identified, and gives faculty and administrators clear, summarized insights into how teaching, services, and facilities are being received.

Key Features
📝 Anonymous student evaluation form: students can submit feedback without revealing their identity
🤖 Automated sentiment analysis: comments are classified using a fine-tuned mBERT model
🌐 Multilingual support: mBERT handles text in multiple languages, including mixed-language comments
🗂️ Multiple evaluation categories: faculty, staff, facilities, and payments
👩‍🏫 Faculty dashboard: faculty view feedback and sentiment results for their own evaluations
🛠️ Admin dashboard: administrators view evaluation result charts across all categories
📊 Visual reports: sentiment distribution and summaries presented in charts for each category
User Roles
Role	Access
Admin	Views evaluation result charts across all categories (faculty, staff, facilities, and payments). Account management is not yet available (see Roadmap)
Faculty	Logs in to view the evaluations and sentiment results for their own classes only
Student	Submits the evaluation form anonymously; no identifying information is attached to the submitted feedback
How It Works
Student submits an evaluation form (ratings and written comments for faculty, staff, facilities, and payments) anonymously.
The comment text is preprocessed (cleaned and tokenized).
The mBERT model predicts the sentiment of each comment (e.g., positive, neutral, negative).
Results are stored alongside the evaluation, without any link to the student's identity.
Faculty and admins view the aggregated results on their dashboards. Faculty see results for their own classes, while admins see charts for every category.
Student Form  ->  Preprocessing  ->  mBERT Model  ->  Sentiment Label  ->  Dashboards
 (anonymous)                                                          (Faculty / Admin)
Sentiment Analysis Model
Item	Details
Base model	bert-base-multilingual-cased (mBERT)
Task	Sentiment classification of student feedback comments
Labels	Positive / Neutral / Negative (edit to match your labels)
Training data	(Describe your dataset: source, size, language(s))
Fine-tuning	(Epochs, batch size, learning rate, framework)
Performance	Accuracy: __% · Precision: __% · Recall: __% · F1: __%

Fill in the table above with the results from your study.

Tech Stack
Area	Technology
Frontend	(e.g., HTML/CSS/JS, React)
Backend	(e.g., Python Flask / Django / FastAPI, PHP, Node.js)
Machine Learning	mBERT, Hugging Face Transformers, PyTorch/TensorFlow
Database	(e.g., MySQL, PostgreSQL, Firebase)
Hosting	(e.g., Render, Vercel, cPanel, PythonAnywhere)
Getting Started
Prerequisites
Python 3.9 or later
pip
Git
A database server (e.g., MySQL)
Installation
Clone the repository
bash
git clone https://github.com/your-username/echosent.git
cd echosent
Create and activate a virtual environment
bash
python -m venv venv
source venv/bin/activate      # On Windows: venv\Scripts\activate
Install dependencies
bash
pip install -r requirements.txt
Set up environment variables
bash
cp .env.example .env

Then edit .env with your own values (see Configuration).

Download or place the trained model Place the fine-tuned mBERT model files in the model/ folder, or download them from (link to your model).
Set up the database
bash
# Example; adjust to your framework
python manage.py migrate
Run the application
bash
python app.py
Open http://localhost:5000 in your browser.
Default Accounts

Create the first admin account with:

bash
# Replace with the command or script your system uses
python create_admin.py

⚠️ Change any default passwords immediately after first login.

Project Structure
echosent/
├── app/
│   ├── routes/          # Admin, faculty, and student routes
│   ├── templates/       # HTML pages (dashboards, evaluation form)
│   └── static/          # CSS, JavaScript, images
├── model/               # Fine-tuned mBERT model files
├── notebooks/           # Training and evaluation notebooks
├── data/                # Dataset (if shareable)
├── .env.example         # Example environment variables
├── requirements.txt
└── README.md

Update this tree to match your actual folders.

Configuration

Create a .env file in the project root:

env
SECRET_KEY=your_secret_key_here
DATABASE_URL=your_database_url_here
MODEL_PATH=./model
DEBUG=False

⚠️ Never commit your .env file or share secret keys publicly.

Privacy and Anonymity

Protecting student identity is central to the system's design:

Evaluation submissions are not linked to student accounts or personal identifiers.
Faculty can only see feedback for their own classes.
Only administrators can view system-wide results across all categories.
Data is used for research and evaluation purposes only.
Roadmap
[x] Anonymous student evaluation form
[x] mBERT sentiment analysis of comments
[x] Faculty dashboard
[x] Admin dashboard with result charts for faculty, staff, facilities, and payments
[ ] Admin account management (create, edit, and deactivate faculty and admin accounts)
[ ] Evaluation period management
[ ] Exportable reports (PDF / CSV)
Research Team
Name	Role
Member name	Lead Developer
Member name	Machine Learning
Member name	Documentation
Adviser name	Research Adviser

Institution: (Your school / university / department)

License

This project was developed for academic research purposes. (Specify your license, e.g., MIT, or "All rights reserved" if preferred.)

Contact
Email: your-email@example.com
GitHub: @your-username
<p align="center">Echosent · Student feedback, made clearer with sentiment analysis</p>
