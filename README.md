# Asiatech Student Sentiment Analysis System

A **web-based student feedback evaluation and sentiment analysis system** developed for **Asia Technological School of Science and Arts (Asiatech), Sta. Rosa, Laguna, Philippines**.

The system collects student evaluations and analyzes open-ended feedback using **SVM, Naive Bayes and Logistic Regression (TF-IDF) alongside Multilingual MiniLM**, then serves the live classification as **Positive, Neutral, or Negative**.

---

## Features

### Student

* **Student login** using student number
* **Likert-scale evaluations**
* **Open-ended feedback**
* Evaluation of:

  * Faculty
  * Staff
  * Payment Services
  * School Facilities
* **Automatic sentiment analysis**

### Faculty

* **Faculty account access**
* View **sentiment analysis results**

### Administrator

* **Administrator authentication**
* **Dataset management**
* Dataset import
* **Training results import and model comparison**
* **Model performance comparison**
* Classification reports
* Confusion matrices
* Prediction results
* Training history

---

## Sentiment Analysis

The system compares **four machine learning approaches** on identical train/test splits.

| Model                        | Role                                                                        |
| ---------------------------- | --------------------------------------------------------------------------- |
| **SVM (TF-IDF)**             | Linear support-vector classifier over TF-IDF features (research/comparison)  |
| **Naive Bayes (TF-IDF)**     | Multinomial Naive Bayes over TF-IDF features (research/comparison)           |
| **Logistic Regression (TF-IDF)** | Linear logistic classifier over TF-IDF features (research/comparison)    |
| **Multilingual MiniLM**      | Fine-tuned sentence-transformer served as a quantized ONNX model — the **only live production model** |

### Production inference

The classical TF-IDF models (SVM, Naive Bayes, Logistic Regression) are
**offline research baselines** — they are trained/evaluated outside the API
(Colab or `scripts/train_models.py`) and shown in the admin comparison view
only. Live predictions are always produced by **Multilingual MiniLM**; there
is no fallback model (a failed MiniLM load returns HTTP 503).

---

## Technology Stack

### Backend

* **Python**
* **FastAPI**
* **SQLAlchemy**
* **MySQL**
* **Alembic**
* **JWT**

### Machine Learning / NLP

* **Scikit-learn** (SVM, Naive Bayes, Logistic Regression)
* **Multilingual MiniLM** (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`)
* **ONNX Runtime** (quantized live inference)
* **Hugging Face Transformers**
* **PyTorch**
* **TF-IDF**
* **NLTK**
* **spaCy**
* **Joblib**

### Frontend

* **HTML5**
* **CSS3**
* **JavaScript**
* **Chart.js**

---

## Project Structure

![Project Structure](https://github.com/user-attachments/assets/52678679-eea2-4945-b4b1-d8986c8e58f1)

---

## System Architecture

![SSAS System Architecture](https://github.com/user-attachments/assets/895a4fb8-eff1-4277-9ff8-1e7b603a275c)

Full written architecture — layers, deployment topology, data model, request flows,
security controls, environment-variable reference, and a PuTTY-based server
access/deployment runbook — is in **[SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md)**.

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/rowseiyyyy/Student-Sentiment-Analysis-System.git
cd Student-Sentiment-Analysis-System
```

### 2. Create a Virtual Environment

```bash
python -m venv .venv
```

Activate the virtual environment:

```powershell
.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy:

```text
backend/.env.example
```

to:

```text
backend/.env
```

Configure the **database and application settings** inside `.env`.

### 5. Run Database Migrations

```bash
alembic upgrade head
```

### 6. Run the System

From the project root:

```bash
python run.py
```

---

## Testing

Run the backend tests:

```bash
cd backend
pytest
```

---

## Model Evaluation

The system supports model evaluation using:

* **Accuracy**
* **Precision**
* **Recall**
* **F1-score**
* **Confusion Matrix**
* **Classification Report**

These metrics are used to compare model performance and evaluate the effectiveness of the sentiment analysis system.

---

## Research Project

* **Project:** Student Sentiment Analysis System
* **Institution:** Asia Technological School of Science and Arts (Asiatech)
* **Location:** Sta. Rosa, Laguna, Philippines

### Researchers

* **Rosemay N. Lorena**
* **Queenie Mae C. Libres**
* **Justin Rey Q. Agapito**

---

## Project Overview

The **Asiatech Student Sentiment Analysis System (SSAS)** provides an automated platform for collecting and analyzing student feedback.

By combining **traditional machine learning** with **transformer-based NLP models**, the system aims to provide a more comprehensive analysis of student sentiment and support the evaluation of **Faculty, Staff, Payment Services, and School Facilities**.


