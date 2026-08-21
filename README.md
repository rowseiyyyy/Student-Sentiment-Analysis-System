Asiatech Student Sentiment Analysis System

A web-based student feedback evaluation and sentiment analysis system developed for Asia Technological School of Science and Arts (Asiatech), Sta. Rosa, Laguna, Philippines.

The system collects student evaluations and analyzes open-ended feedback using XGBoost, DeBERTa, and RoBERTa, combined through a weighted soft-voting ensemble to classify feedback as Positive, Neutral, or Negative.

Features
Student
Student login using student number
Likert-scale evaluations
Open-ended feedback
Evaluation of Faculty, Staff, Payment Services, and School Facilities
Automatic sentiment analysis
Faculty
Faculty account access
View student evaluation results
Administrator
Administrator authentication
Dataset management
Dataset import
Model training and retraining
Model performance comparison
Classification reports
Confusion matrices
Prediction results
Training history
Sentiment Analysis

The system uses three machine learning models:

Model	Role
XGBoost	Traditional machine learning model using TF-IDF
DeBERTa	Transformer-based sentiment classifier
RoBERTa	Transformer-based sentiment classifier
Weighted Ensemble
Student Feedback
       ↓
Validation
       ↓
Preprocessing
       ↓
 ┌──────────┬──────────┬──────────┐
 │ XGBoost  │ DeBERTa  │ RoBERTa  │
 │  20%     │   40%    │   40%    │
 └──────────┴──────────┴──────────┘
       ↓
Weighted Soft Voting
       ↓
Final Sentiment
       ↓
Positive / Neutral / Negative
Technology Stack
Backend
Python
FastAPI
SQLAlchemy
MySQL
Alembic
JWT
Machine Learning / NLP
XGBoost
Hugging Face Transformers
PyTorch
DeBERTa
RoBERTa
Scikit-learn
TF-IDF
NLTK
spaCy
Joblib
Frontend
HTML5
CSS3
JavaScript
Chart.js
Project Structure
Student-Sentiment-Analysis-System/
│
├── backend/
│   ├── alembic/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── datasets/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── deberta_service.py
│   │   │   ├── ensembles.py
│   │   │   ├── preprocessing.py
│   │   │   ├── roberta_service.py
│   │   │   ├── training.py
│   │   │   └── xgboost_service.py
│   │   └── utils/
│   ├── tests/
│   ├── scripts/
│   ├── requirements.txt
│   └── main.py
│
├── frontend/
│   ├── css/
│   ├── js/
│   └── index.html
│
├── .gitignore
├── TODO.md
├── folder-structure.txt
└── run.py
Installation
1. Clone the repository
git clone https://github.com/rowseiyyyy/Student-Sentiment-Analysis-System.git
cd Student-Sentiment-Analysis-System
2. Create a virtual environment
python -m venv .venv

Activate it:

.venv\Scripts\Activate.ps1
3. Install dependencies
cd backend
pip install -r requirements.txt
4. Configure environment variables

Copy:

backend/.env.example

to:

backend/.env

Configure the database and application settings in .env.

5. Run database migrations
alembic upgrade head
6. Run the system

From the project root:

python run.py
Testing

Run the backend tests:

cd backend
pytest
Model Evaluation

The system supports evaluation using:

Accuracy
Precision
Recall
F1-score
Confusion Matrix
Classification Report
Research Project

Project: Student Sentiment Analysis System
Institution: Asia Technological School of Science and Arts (Asiatech)
Location: Sta. Rosa, Laguna, Philippines

Researchers
Rosemay N. Lorena
Queenie Mae C. Libres
Justin Rey Q. Agapito

