"""
Автоподсказка запчастей: поиск похожих ремонтов по тексту комментария
в истории ремонтов (TF-IDF + косинусная близость), агрегация запчастей
из наиболее похожих прошлых случаев.
"""
from collections import Counter

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from data_prep import parse_parts_string


class PartsSuggester:
    def __init__(self, history_df):
        corpus_df = history_df[
            history_df["comment"].notna() & history_df["parts"].notna()
        ].reset_index(drop=True)
        self.corpus_df = corpus_df
        self.comments = corpus_df["comment"].astype(str).tolist()

        self.vectorizer = TfidfVectorizer(
            token_pattern=r"(?u)\b\w+\b",
            ngram_range=(1, 2),
            min_df=1,
        )
        if self.comments:
            self.matrix = self.vectorizer.fit_transform(self.comments)
        else:
            self.matrix = None

    def suggest(self, query_text: str, top_k: int = 5, max_parts: int = 8):
        """Возвращает (список запчастей [(name, count_in_matches)], список похожих случаев для показа)."""
        if not query_text or not query_text.strip() or self.matrix is None:
            return [], []

        query_vec = self.vectorizer.transform([query_text])
        sims = cosine_similarity(query_vec, self.matrix).flatten()

        top_idx = sims.argsort()[::-1][:top_k]
        top_idx = [i for i in top_idx if sims[i] > 0.05]  # отсекаем совсем нерелевантное

        parts_counter = Counter()
        similar_cases = []
        for i in top_idx:
            row = self.corpus_df.iloc[i]
            items = parse_parts_string(row["parts"])
            for name, qty in items:
                parts_counter[name] += 1
            similar_cases.append({
                "comment": row["comment"],
                "parts": row["parts"],
                "similarity": round(float(sims[i]), 2),
                "sn": row.get("sn_norm", ""),
            })

        ranked_parts = [name for name, _ in parts_counter.most_common(max_parts)]
        return ranked_parts, similar_cases
