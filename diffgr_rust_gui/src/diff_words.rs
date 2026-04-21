//! Word-level diff helpers used by the native GUI diff viewer.

use std::collections::BTreeSet;

pub const MAX_WORD_DIFF_LINE_CHARS: usize = 4096;
pub const MAX_WORD_DIFF_TOKENS: usize = 768;
pub const MAX_LINE_PAIR_CANDIDATES: usize = 2048;
pub const LINE_PAIR_SIMILARITY_THRESHOLD: f32 = 0.12;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DiffTextSegment {
    pub text: String,
    pub changed: bool,
}

impl DiffTextSegment {
    pub fn new(text: impl Into<String>, changed: bool) -> Self {
        Self {
            text: text.into(),
            changed,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct LineMatch {
    pub old_index: usize,
    pub new_index: usize,
    pub score: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum TokenClass {
    Whitespace,
    Word,
    Punctuation,
}

fn token_class(ch: char) -> TokenClass {
    if ch.is_whitespace() {
        TokenClass::Whitespace
    } else if ch.is_alphanumeric() {
        TokenClass::Word
    } else {
        TokenClass::Punctuation
    }
}

fn should_split_word(prev: char, next: char) -> bool {
    if !prev.is_alphanumeric() || !next.is_alphanumeric() {
        return true;
    }
    if prev.is_lowercase() && next.is_uppercase() {
        return true;
    }
    if prev.is_ascii_alphabetic() && next.is_ascii_digit() {
        return true;
    }
    if prev.is_ascii_digit() && next.is_ascii_alphabetic() {
        return true;
    }
    false
}

pub fn tokenize_for_word_diff(text: &str) -> Vec<String> {
    let mut tokens = Vec::new();
    let mut current = String::new();
    let mut current_class: Option<TokenClass> = None;
    let mut previous_char: Option<char> = None;
    for ch in text.chars() {
        let class = token_class(ch);
        let split = match (current_class, class, previous_char) {
            (None, _, _) => false,
            (Some(TokenClass::Punctuation), _, _) => true,
            (_, TokenClass::Punctuation, _) => true,
            (Some(TokenClass::Word), TokenClass::Word, Some(prev)) => should_split_word(prev, ch),
            (Some(existing), next, _) => existing != next,
        };
        if split && !current.is_empty() {
            tokens.push(std::mem::take(&mut current));
        }
        current.push(ch);
        current_class = Some(class);
        previous_char = Some(ch);
    }
    if !current.is_empty() {
        tokens.push(current);
    }
    tokens
}

fn non_ws_tokens(text: &str) -> Vec<String> {
    tokenize_for_word_diff(text)
        .into_iter()
        .filter(|token| !token.chars().all(char::is_whitespace))
        .map(|token| token.to_lowercase())
        .collect()
}

fn lcs_len<T: Eq>(old: &[T], new: &[T]) -> usize {
    if old.is_empty() || new.is_empty() {
        return 0;
    }
    let mut prev = vec![0usize; new.len() + 1];
    let mut curr = vec![0usize; new.len() + 1];
    for old_item in old {
        for (j, new_item) in new.iter().enumerate() {
            curr[j + 1] = if old_item == new_item {
                prev[j] + 1
            } else {
                curr[j].max(prev[j + 1])
            };
        }
        std::mem::swap(&mut prev, &mut curr);
        curr.fill(0);
    }
    prev[new.len()]
}

fn lcs_unchanged_flags<T: Eq>(old: &[T], new: &[T]) -> (Vec<bool>, Vec<bool>) {
    let n = old.len();
    let m = new.len();
    let mut table = vec![0usize; (n + 1) * (m + 1)];
    let idx = |i: usize, j: usize| i * (m + 1) + j;
    for i in 0..n {
        for j in 0..m {
            table[idx(i + 1, j + 1)] = if old[i] == new[j] {
                table[idx(i, j)] + 1
            } else {
                table[idx(i, j + 1)].max(table[idx(i + 1, j)])
            };
        }
    }
    let mut old_unchanged = vec![false; n];
    let mut new_unchanged = vec![false; m];
    let mut i = n;
    let mut j = m;
    while i > 0 && j > 0 {
        if old[i - 1] == new[j - 1] {
            old_unchanged[i - 1] = true;
            new_unchanged[j - 1] = true;
            i -= 1;
            j -= 1;
        } else if table[idx(i - 1, j)] >= table[idx(i, j - 1)] {
            i -= 1;
        } else {
            j -= 1;
        }
    }
    (old_unchanged, new_unchanged)
}

fn segments_from_tokens(tokens: &[String], unchanged: &[bool]) -> Vec<DiffTextSegment> {
    let mut segments: Vec<DiffTextSegment> = Vec::new();
    for (token, same) in tokens.iter().zip(unchanged.iter().copied()) {
        let changed = !same;
        if let Some(last) = segments.last_mut() {
            if last.changed == changed {
                last.text.push_str(token);
                continue;
            }
        }
        segments.push(DiffTextSegment::new(token.clone(), changed));
    }
    segments
}

pub fn word_level_segments(
    old: &str,
    new: &str,
) -> Option<(Vec<DiffTextSegment>, Vec<DiffTextSegment>)> {
    if old.chars().count() > MAX_WORD_DIFF_LINE_CHARS
        || new.chars().count() > MAX_WORD_DIFF_LINE_CHARS
    {
        return None;
    }
    let old_tokens = tokenize_for_word_diff(old);
    let new_tokens = tokenize_for_word_diff(new);
    if old_tokens.len() > MAX_WORD_DIFF_TOKENS || new_tokens.len() > MAX_WORD_DIFF_TOKENS {
        return None;
    }
    let (old_unchanged, new_unchanged) = lcs_unchanged_flags(&old_tokens, &new_tokens);
    Some((
        segments_from_tokens(&old_tokens, &old_unchanged),
        segments_from_tokens(&new_tokens, &new_unchanged),
    ))
}

pub fn line_similarity(old: &str, new: &str) -> f32 {
    if old == new {
        return 1.0;
    }
    let old_tokens = non_ws_tokens(old);
    let new_tokens = non_ws_tokens(new);
    if old_tokens.is_empty() && new_tokens.is_empty() {
        return 1.0;
    }
    if old_tokens.is_empty() || new_tokens.is_empty() {
        return 0.0;
    }
    if old_tokens.len() > MAX_WORD_DIFF_TOKENS || new_tokens.len() > MAX_WORD_DIFF_TOKENS {
        let old_set: BTreeSet<_> = old_tokens.iter().collect();
        let new_set: BTreeSet<_> = new_tokens.iter().collect();
        let intersection = old_set.intersection(&new_set).count() as f32;
        let union = old_set.union(&new_set).count() as f32;
        return if union == 0.0 {
            0.0
        } else {
            intersection / union
        };
    }
    let common = lcs_len(&old_tokens, &new_tokens) as f32;
    (2.0 * common) / (old_tokens.len() as f32 + new_tokens.len() as f32)
}

pub fn match_delete_add_pairs<F>(
    deletes: &[usize],
    adds: &[usize],
    mut text_at: F,
) -> Vec<LineMatch>
where
    F: FnMut(usize) -> Option<String>,
{
    if deletes.is_empty() || adds.is_empty() {
        return Vec::new();
    }
    if deletes.len().saturating_mul(adds.len()) > MAX_LINE_PAIR_CANDIDATES {
        return deletes
            .iter()
            .copied()
            .zip(adds.iter().copied())
            .map(|(old_index, new_index)| LineMatch {
                old_index,
                new_index,
                score: 0.5,
            })
            .collect();
    }
    let mut candidates = Vec::new();
    for &old_index in deletes {
        let Some(old_text) = text_at(old_index) else {
            continue;
        };
        for &new_index in adds {
            let Some(new_text) = text_at(new_index) else {
                continue;
            };
            let score = line_similarity(&old_text, &new_text);
            if score >= LINE_PAIR_SIMILARITY_THRESHOLD {
                candidates.push(LineMatch {
                    old_index,
                    new_index,
                    score,
                });
            }
        }
    }
    candidates.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.old_index.cmp(&b.old_index))
            .then_with(|| a.new_index.cmp(&b.new_index))
    });
    let mut used_old = BTreeSet::new();
    let mut used_new = BTreeSet::new();
    let mut matches = Vec::new();
    for candidate in candidates {
        if used_old.contains(&candidate.old_index) || used_new.contains(&candidate.new_index) {
            continue;
        }
        used_old.insert(candidate.old_index);
        used_new.insert(candidate.new_index);
        matches.push(candidate);
    }
    matches.sort_by(|a, b| {
        a.old_index
            .cmp(&b.old_index)
            .then_with(|| a.new_index.cmp(&b.new_index))
    });
    matches
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tokenizer_splits_code_identifiers_and_punctuation() {
        assert_eq!(
            tokenize_for_word_diff("userID = old_value + 1"),
            vec!["user", "ID", " ", "=", " ", "old", "_", "value", " ", "+", " ", "1"]
        );
    }

    #[test]
    fn word_level_segments_highlight_only_changed_tokens() {
        let (old, new) = word_level_segments("let count = 1;", "let count = 2;").unwrap();
        assert!(old
            .iter()
            .any(|segment| segment.text == "1" && segment.changed));
        assert!(new
            .iter()
            .any(|segment| segment.text == "2" && segment.changed));
        assert!(new
            .iter()
            .any(|segment| segment.text.contains("let count = ") && !segment.changed));
    }

    #[test]
    fn line_similarity_prefers_related_lines() {
        let related = line_similarity("let count = old_total + 1;", "let count = new_total + 1;");
        let unrelated = line_similarity("fn main() {", "return cachedUser;");
        assert!(related > unrelated);
        assert!(related > 0.5);
    }

    #[test]
    fn match_delete_add_pairs_uses_best_similarity() {
        let lines = [
            "fn alpha()",
            "return beta",
            "fn alpha_new()",
            "return gamma",
        ];
        let matches =
            match_delete_add_pairs(&[0, 1], &[2, 3], |index| Some(lines[index].to_owned()));
        assert_eq!(matches[0].old_index, 0);
        assert_eq!(matches[0].new_index, 2);
    }
}
