//! 混合检索：稀疏(BM25 式)召回 + RRF 融合排序
//! 与向量检索互补：向量管语义相似，关键词管公式/题号/专有名词的精确匹配。

use std::collections::{HashMap, HashSet};

/// 中文表意字符（CJK 统一表意文字）
fn is_cjk(c: char) -> bool {
    let u = c as u32;
    (0x3400..=0x4DBF).contains(&u) || (0x4E00..=0x9FFF).contains(&u)
}

/// 分词：CJK 连续段按 2-gram 切分，ASCII 字母数字按连续串切分（小写）
pub fn tokenize(text: &str) -> Vec<String> {
    let chars: Vec<char> = text.chars().collect();
    let mut tokens = Vec::new();
    let mut i = 0;
    while i < chars.len() {
        if chars[i].is_ascii_alphanumeric() {
            let start = i;
            while i < chars.len() && chars[i].is_ascii_alphanumeric() {
                i += 1;
            }
            tokens.push(chars[start..i].iter().collect::<String>().to_lowercase());
        } else if is_cjk(chars[i]) {
            let start = i;
            while i < chars.len() && is_cjk(chars[i]) {
                i += 1;
            }
            let run: Vec<char> = chars[start..i].to_vec();
            if run.len() == 1 {
                tokens.push(run[0].to_string());
            } else {
                for w in run.windows(2) {
                    tokens.push(format!("{}{}", w[0], w[1]));
                }
            }
        } else {
            i += 1;
        }
    }
    tokens
}

/// BM25 式稀疏打分（k1=1.5, b=0.75）。docs: (doc_id, 文本)
pub fn bm25_scores(docs: &[(i64, String)], query: &str) -> Vec<(i64, f32)> {
    const K1: f32 = 1.5;
    const B: f32 = 0.75;

    let mut doc_tokens: Vec<Vec<String>> = Vec::with_capacity(docs.len());
    let mut doc_lens: Vec<usize> = Vec::with_capacity(docs.len());
    let mut df: HashMap<String, u32> = HashMap::new();

    for (_, text) in docs {
        let toks = tokenize(text);
        doc_tokens.push(toks.clone());
        doc_lens.push(toks.len());
        let mut seen = HashSet::new();
        for t in &toks {
            if seen.insert(t.clone()) {
                *df.entry(t.clone()).or_insert(0) += 1;
            }
        }
    }
    let n = docs.len().max(1) as f32;
    let avgdl: f32 = if doc_lens.is_empty() {
        1.0
    } else {
        doc_lens.iter().sum::<usize>() as f32 / doc_lens.len() as f32
    };

    let q_tokens = tokenize(query);
    let mut scores = vec![0.0f32; docs.len()];
    for term in &q_tokens {
        let df_t = *df.get(term).unwrap_or(&0);
        let idf = ((n - df_t as f32 + 0.5) / (df_t as f32 + 0.5) + 1.0).ln();
        for (i, doc) in doc_tokens.iter().enumerate() {
            let tf = doc.iter().filter(|t| *t == term).count() as f32;
            if tf == 0.0 {
                continue;
            }
            let dl = doc_lens[i] as f32;
            let denom = tf + K1 * (1.0 - B + B * dl / avgdl);
            scores[i] += idf * (tf * (K1 + 1.0)) / denom;
        }
    }

    docs.iter()
        .enumerate()
        .map(|(i, (id, _))| (*id, scores[i]))
        .collect()
}

/// RRF 融合：输入若干按分数降序的榜单，按名次加权累加（k 常取 60）
pub fn rrf_fuse(lists: &[Vec<(i64, f32)>], k: f32) -> Vec<(i64, f32)> {
    let mut acc: HashMap<i64, f32> = HashMap::new();
    for list in lists {
        for (rank, (id, _)) in list.iter().enumerate() {
            *acc.entry(*id).or_insert(0.0) += 1.0 / (k + rank as f32 + 1.0);
        }
    }
    let mut v: Vec<(i64, f32)> = acc.into_iter().collect();
    v.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    v
}

/// 预构建的 BM25 语料：一次性分词并统计 df/avgdl，供多次查询复用，
/// 避免对同一批文档反复 tokenize（缓存单元）。
#[derive(Clone)]
pub struct Bm25Corpus {
    doc_ids: Vec<i64>,
    doc_tokens: Vec<Vec<String>>,
    doc_lens: Vec<usize>,
    df: HashMap<String, u32>,
    n: f32,
    avgdl: f32,
}

impl Bm25Corpus {
    /// 从文档构建语料（docs: (doc_id, 文本)）
    pub fn build(docs: &[(i64, String)]) -> Self {
        let mut doc_tokens: Vec<Vec<String>> = Vec::with_capacity(docs.len());
        let mut doc_lens: Vec<usize> = Vec::with_capacity(docs.len());
        let mut df: HashMap<String, u32> = HashMap::new();
        for (_, text) in docs {
            let toks = tokenize(text);
            doc_lens.push(toks.len());
            let mut seen = HashSet::new();
            for t in &toks {
                if seen.insert(t.clone()) {
                    *df.entry(t.clone()).or_insert(0) += 1;
                }
            }
            doc_tokens.push(toks);
        }
        let n = docs.len().max(1) as f32;
        let avgdl: f32 = if doc_lens.is_empty() {
            1.0
        } else {
            doc_lens.iter().sum::<usize>() as f32 / doc_lens.len() as f32
        };
        Self {
            doc_ids: docs.iter().map(|(id, _)| *id).collect(),
            doc_tokens,
            doc_lens,
            df,
            n,
            avgdl,
        }
    }

    /// 对查询打分，返回 (doc_id, score)，与 `bm25_scores` 同口径
    pub fn score(&self, query: &str) -> Vec<(i64, f32)> {
        const K1: f32 = 1.5;
        const B: f32 = 0.75;
        let q_tokens = tokenize(query);
        let mut scores = vec![0.0f32; self.doc_tokens.len()];
        for term in &q_tokens {
            let df_t = *self.df.get(term).unwrap_or(&0);
            let idf = ((self.n - df_t as f32 + 0.5) / (df_t as f32 + 0.5) + 1.0).ln();
            for (i, doc) in self.doc_tokens.iter().enumerate() {
                let tf = doc.iter().filter(|t| *t == term).count() as f32;
                if tf == 0.0 {
                    continue;
                }
                let dl = self.doc_lens[i] as f32;
                let denom = tf + K1 * (1.0 - B + B * dl / self.avgdl);
                scores[i] += idf * (tf * (K1 + 1.0)) / denom;
            }
        }
        self.doc_ids
            .iter()
            .copied()
            .zip(scores)
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tokenize_ascii_and_cjk() {
        let toks = tokenize("勾股定理 a^2+b^2=c^2");
        assert!(toks.contains(&"勾股".to_string()));
        assert!(toks.contains(&"定理".to_string()));
        assert!(toks.contains(&"a".to_string()));
        assert!(toks.contains(&"2".to_string()));
    }

    #[test]
    fn test_tokenize_single_cjk_char_is_kept() {
        let toks = tokenize("求解");
        // 两个 CJK 字符 → 一个 2-gram
        assert_eq!(toks, vec!["求解".to_string()]);
    }

    #[test]
    fn test_bm25_prefers_exact_match_doc() {
        let docs = vec![
            (1, "一元二次方程求解 x^2-5x+6=0".to_string()),
            (2, "勾股定理 三角形 直角".to_string()),
        ];
        let scores = bm25_scores(&docs, "一元二次方程");
        let (top_id, _) = scores
            .iter()
            .max_by(|a, b| a.1.partial_cmp(&b.1).unwrap())
            .expect("non-empty");
        assert_eq!(*top_id, 1);
        let (_id2, s2) = scores.iter().find(|(id, _)| *id == 2).expect("doc2");
        assert!(scores.iter().find(|(id, _)| *id == 1).unwrap().1 > *s2);
    }

    #[test]
    fn test_bm25_empty_query_returns_zero() {
        let docs = vec![(1, "勾股定理".to_string())];
        let scores = bm25_scores(&docs, "");
        assert_eq!(scores, vec![(1, 0.0)]);
    }

    #[test]
    fn test_rrf_fuses_and_ranks() {
        let vector = vec![(1, 0.9), (2, 0.8), (3, 0.7)];
        let keyword = vec![(2, 3.0), (4, 2.0)];
        let fused = rrf_fuse(&[vector, keyword], 60.0);
        // id2 在两个榜单都靠前 → 应排第一
        assert_eq!(fused[0].0, 2);
        assert!(fused.iter().any(|(id, _)| *id == 1));
        assert!(fused.iter().any(|(id, _)| *id == 3));
    }

    #[test]
    fn test_rrf_single_list_preserves_order() {
        let vector = vec![(5, 0.9), (6, 0.8)];
        let fused = rrf_fuse(&[vector], 60.0);
        assert_eq!(fused, vec![(5, 1.0 / 61.0), (6, 1.0 / 62.0)]);
    }

    #[test]
    fn test_bm25_corpus_matches_bm25_scores() {
        let docs = vec![
            (1, "一元二次方程求解 x^2-5x+6=0".to_string()),
            (2, "勾股定理 三角形 直角".to_string()),
            (3, "一元二次方程 配方".to_string()),
        ];
        let corpus = Bm25Corpus::build(&docs);
        let direct = bm25_scores(&docs, "一元二次方程");
        let cached = corpus.score("一元二次方程");
        // 同 id 对应分数一致（允许浮点误差）
        for (id, s_cached) in &cached {
            let s_direct = direct
                .iter()
                .find(|(did, _)| did == id)
                .map(|(_, s)| *s)
                .unwrap_or(0.0);
            assert!((s_cached - s_direct).abs() < 1e-5, "id {} 分数不一致", id);
        }
        // 多次调用结果稳定（缓存价值体现）
        let cached2 = corpus.score("一元二次方程");
        assert_eq!(cached2, cached);
    }
}