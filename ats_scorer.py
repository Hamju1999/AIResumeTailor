"""ATS Scorer - keyword extraction and match scoring."""
from __future__ import annotations
import re
from dataclasses import dataclass, field

_STOP = {
    "a","an","the","and","or","but","if","in","on","at","to","for","of","with",
    "by","from","as","is","are","was","were","be","been","being","have","has",
    "had","do","does","did","will","would","could","should","may","might","shall",
    "not","no","nor","so","yet","both","either","neither","each","few","more",
    "most","other","some","such","than","that","this","these","those","its","our",
    "your","their","we","you","they","he","she","it","who","which","what","how",
    "when","where","why","all","any","both","each","every","few","much","many",
    "own","same","too","very","just","about","above","across","after","against",
    "also","well","good","great","strong","high","large","small","key",
    "excellent","equivalent","relevant","related","including","based","using",
    "working","across","multiple","various","etc","please","apply","join","team",
    "company","position","role","opportunity","looking","seeking","candidate",
    "required","requirements","plus","bonus","preferred","nice","able","ability",
    "work","minimum","years","year","experience","field","areas","knowledge",
    "understanding","familiarity","demonstrated","proven","solid","hands","degree",
    "bachelor","master","phd","science","engineering","mathematics","statistics",
    "problem","solving","analytical","communication","skills","skill","written",
    "verbal","interpersonal","collaborative","detail","oriented","motivated",
    "fast","paced","environment","startup","responsibilities","duties","tasks",
    "us","ca","inc","llc","corp","ltd","hiring","grad","new","junior","senior",
    "level","like","via","per","day","week","month","build","use","make","get",
    "give","take","come","go","see","know","think","want","need","help","learn",
    "grow","lead","manage","own","drive","impact","cross","functional",
}

_KNOWN_PHRASES = {
    "machine learning","deep learning","natural language processing",
    "computer vision","reinforcement learning","generative ai",
    "large language model","neural network","random forest",
    "gradient boosting","decision tree","logistic regression",
    "linear regression","time series","anomaly detection",
    "feature engineering","model training","model evaluation",
    "model deployment","transfer learning","fine tuning",
    "prompt engineering","retrieval augmented","vector database",
    "a/b testing","hypothesis testing","statistical modeling",
    "statistical analysis","predictive modeling","dimensionality reduction",
    "data science","data engineering","data analysis","data analytics",
    "data pipeline","data warehouse","data visualization","data quality",
    "data modeling","data lake","etl pipeline","data ingestion",
    "real time","batch processing","stream processing",
    "apache spark","apache kafka","apache airflow","apache hadoop",
    "google cloud","amazon web","azure ml","aws s3","aws lambda",
    "aws sagemaker","power bi","rest api","version control",
    "business intelligence","fraud detection","risk modeling",
    "churn prediction","credit scoring","object oriented",
    "distributed computing","sql query","stored procedure",
    "continuous integration","continuous deployment",
    "sentiment analysis","text classification","named entity",
    "recommendation system","search ranking",
}

_HARD_SKILLS = {
    "python","sql","r","java","scala","javascript","typescript","go","rust",
    "spark","kafka","airflow","dbt","snowflake","redshift",
    "bigquery","databricks","tableau","looker","powerbi","matplotlib","seaborn",
    "plotly","sklearn","scikit","tensorflow","pytorch","keras","pandas","numpy",
    "pyspark","hadoop","hive","postgres","mysql","mongodb","elasticsearch",
    "redis","docker","kubernetes","terraform","aws","gcp","azure","github",
    "flask","fastapi","django","streamlit","gradio","jupyter","excel",
    "openai","langchain","huggingface","wandb","mlflow","dvc",
    "tesseract","git","linux","bash",
    "xgboost","lightgbm","catboost","statsmodels","scipy","nltk","spacy",
    "etl","api","nosql","looker","dask","ray","metabase","superset",
}

_SYNONYMS = {
    "ml":                          ["machine learning"],
    "nlp":                         ["natural language processing"],
    "dl":                          ["deep learning"],
    "ai":                          ["artificial intelligence"],
    "bi":                          ["business intelligence"],
    "etl":                         ["data pipeline","etl pipeline"],
    "api":                         ["rest api"],
    "llm":                         ["large language model"],
    "rag":                         ["retrieval augmented"],
    "aws":                         ["amazon web"],
    "gcp":                         ["google cloud"],
    "sklearn":                     ["scikit"],
    "scikit":                      ["sklearn"],
    "powerbi":                     ["power bi"],
    "power bi":                    ["powerbi"],
    "machine learning":            ["ml"],
    "natural language processing": ["nlp"],
    "large language model":        ["llm"],
    "deep learning":               ["dl"],
}

_REQUIREMENTS_RE = re.compile(
    r"(requirement|qualif|responsibilit|what you.ll|must have|"
    r"preferred|you have|you bring|technical skill|nice to have)",
    re.IGNORECASE,
)

_PROPER = {
    "python":"Python","sql":"SQL","r":"R","java":"Java","scala":"Scala",
    "spark":"Spark","kafka":"Kafka","airflow":"Airflow","dbt":"dbt",
    "snowflake":"Snowflake","tableau":"Tableau","aws":"AWS","gcp":"GCP",
    "azure":"Azure","pytorch":"PyTorch","tensorflow":"TensorFlow",
    "sklearn":"scikit-learn","pandas":"Pandas","numpy":"NumPy",
    "docker":"Docker","kubernetes":"Kubernetes","github":"GitHub",
    "flask":"Flask","fastapi":"FastAPI","openai":"OpenAI",
    "etl":"ETL","api":"API","ml":"ML","ai":"AI","nlp":"NLP","bi":"BI",
    "llm":"LLM","rag":"RAG","powerbi":"Power BI",
    "langchain":"LangChain","streamlit":"Streamlit","plotly":"Plotly",
    "xgboost":"XGBoost","lightgbm":"LightGBM","catboost":"CatBoost",
    "pyspark":"PySpark","bigquery":"BigQuery","redshift":"Redshift",
    "databricks":"Databricks","looker":"Looker","mlflow":"MLflow",
    "huggingface":"HuggingFace","tesseract":"Tesseract",
    "linux":"Linux","bash":"Bash","postgres":"PostgreSQL","mysql":"MySQL",
    "mongodb":"MongoDB","elasticsearch":"Elasticsearch","redis":"Redis",
    "hadoop":"Hadoop","scipy":"SciPy","nltk":"NLTK","spacy":"spaCy",
}


@dataclass
class ATSResult:
    score:            int
    above_threshold:  bool
    threshold:        int
    hard_skill_score: int
    matched:          list
    missing:          list
    matched_phrases:  list
    total_checked:    int
    breakdown:        dict = field(default_factory=dict)


def score(jd_text, resume_text, matched_keywords=None, threshold=75):
    jd_norm  = _norm(jd_text)
    res_norm = _norm(resume_text)

    kw_weights = _extract(jd_text, jd_norm)

    if matched_keywords:
        for kw in matched_keywords:
            kn = _norm(kw)
            if kn and len(kn) > 2:
                kw_weights[kn] = max(kw_weights.get(kn, 0), 3.0)

    if not kw_weights:
        return ATSResult(0, False, threshold, 0, [], [], [], 0)

    matched_list = []
    missing_list = []
    phrases_list = []
    total_w = matched_w = hard_total = hard_matched = 0.0

    for kw, weight in sorted(kw_weights.items(), key=lambda x: -x[1]):
        total_w += weight
        is_hard = (kw in _HARD_SKILLS) or (" " in kw)
        if is_hard:
            hard_total += weight

        found = _hit(kw, res_norm)
        if not found:
            for syn in _SYNONYMS.get(kw, []):
                if _hit(_norm(syn), res_norm):
                    found = True
                    break

        if found:
            matched_w += weight
            if is_hard:
                hard_matched += weight
            disp = _disp(kw)
            matched_list.append(disp)
            if " " in kw:
                phrases_list.append(disp)
        else:
            if weight >= 1.5:
                missing_list.append(_disp(kw))

    sv  = min(100, round(matched_w / total_w * 100)) if total_w else 0
    hsv = min(100, round(hard_matched / hard_total * 100)) if hard_total else 0

    return ATSResult(
        score            = sv,
        above_threshold  = sv >= threshold,
        threshold        = threshold,
        hard_skill_score = hsv,
        matched          = matched_list[:25],
        missing          = missing_list[:12],
        matched_phrases  = phrases_list[:12],
        total_checked    = len(kw_weights),
        breakdown        = {"total_keywords": len(kw_weights),
                            "matched_count":  len(matched_list),
                            "hard_skill_score": hsv,
                            "phrase_matches": len(phrases_list)},
    )


def _extract(raw, norm):
    weights = {}
    sections = _sections(raw)
    for section_text, pw in sections:
        sn     = _norm(section_text)
        tokens = sn.split()
        for tok in tokens:
            if tok in _HARD_SKILLS:
                cap = 1.3 if re.search(r"\b" + re.escape(tok.title()) + r"\b", section_text) else 1.0
                weights[tok] = weights.get(tok, 0) + pw * cap
        for i in range(len(tokens) - 1):
            phrase = tokens[i] + " " + tokens[i+1]
            if phrase in _KNOWN_PHRASES:
                weights[phrase] = weights.get(phrase, 0) + pw * 2.0
        for i in range(len(tokens) - 2):
            tri = tokens[i] + " " + tokens[i+1] + " " + tokens[i+2]
            if tri in _KNOWN_PHRASES:
                weights[tri] = weights.get(tri, 0) + pw * 2.5
        for tok in tokens:
            if tok not in _STOP and tok not in _HARD_SKILLS and len(tok) > 3 and tok.isalpha():
                weights[tok] = weights.get(tok, 0) + pw * 0.4
    filtered = {k: v for k, v in weights.items() if v >= 1.0}
    return dict(sorted(filtered.items(), key=lambda x: -x[1])[:50])


def _sections(text):
    lines = text.splitlines()
    header = " ".join(lines[:5])
    result = [(header, 3.0)]
    cur_w, cur = 1.0, []
    for line in lines[5:]:
        if _REQUIREMENTS_RE.search(line):
            if cur:
                result.append((" ".join(cur), cur_w))
                cur = []
            cur_w = 2.0
        cur.append(line)
    if cur:
        result.append((" ".join(cur), cur_w))
    return result


def _norm(text):
    text = text.lower()
    text = re.sub(r"[^\w\s+#./]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _hit(kw, res_norm):
    if not kw or len(kw) < 2:
        return False
    if " " in kw:
        return kw in res_norm
    return bool(re.search(r"\b" + re.escape(kw) + r"\b", res_norm))


def _disp(kw):
    if " " in kw:
        return " ".join(
            _PROPER.get(w, w.title() if len(w) > 2 else w.upper())
            for w in kw.split()
        )
    return _PROPER.get(kw, kw.title() if len(kw) > 2 else kw.upper())
