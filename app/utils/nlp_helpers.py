import logging
import re
from statistics import mean

import spacy


logger = logging.getLogger(__name__)

try:
    _nlp = spacy.load("en_core_web_sm")
except Exception:
    _nlp = spacy.blank("en")
    if "sentencizer" not in _nlp.pipe_names:
        _nlp.add_pipe("sentencizer")


FILLER_WORDS = {
    "um",
    "uh",
    "basically",
    "like",
    "literally",
    "you know",
    "sort of",
    "kind of",
    "right",
    "actually",
    "honestly",
    "i mean",
    "and so",
}


def normalize_transcript(text):
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", str(text).strip().lower())
    cleaned = re.sub(r"[^a-z0-9\s']", "", cleaned)
    return cleaned


def count_filler_words(text):
    normalized = normalize_transcript(text)
    if not normalized:
        return 0

    total_count = 0
    for filler in sorted(FILLER_WORDS, key=len, reverse=True):
        pattern = rf"\b{re.escape(filler)}\b"
        total_count += len(re.findall(pattern, normalized))

    return total_count


def _clamp_score(value):
    return max(0.0, min(100.0, float(value)))


def _clean_word(token_text):
    return re.sub(r"\s+", " ", str(token_text or "")).strip()


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def compute_lexical_diversity(transcript: str, baseline_mattr: float = None) -> float:
    if not transcript:
        return 0.0

    doc = _nlp(transcript)
    lemmas = []
    for token in doc:
        if token.is_alpha:
            lemma = (token.lemma_ or token.text).lower().strip()
            if lemma:
                lemmas.append(lemma)

    if len(lemmas) < 10:
        return 0.0

    window_size = 50
    if len(lemmas) < window_size:
        mattr_value = len(set(lemmas)) / len(lemmas)
    else:
        ttr_values = []
        for index in range(0, len(lemmas) - window_size + 1):
            window = lemmas[index : index + window_size]
            ttr_values.append(len(set(window)) / window_size)
        mattr_value = mean(ttr_values) if ttr_values else 0.0

    if baseline_mattr is not None and baseline_mattr > 0:
        normalized_score = (mattr_value / baseline_mattr) * 100.0
    else:
        normalized_score = mattr_value * 100.0

    return _clamp_score(normalized_score)


def compute_syntactic_complexity(transcript: str) -> float:
    if not transcript:
        return 0.0

    doc = _nlp(transcript)
    sentences = list(doc.sents)
    if not sentences:
        return 0.0

    sentence_lengths = []
    for sentence in sentences:
        token_count = len(
            [token for token in sentence if not token.is_punct and not token.is_space]
        )
        if token_count > 0:
            sentence_lengths.append(token_count)

    if not sentence_lengths:
        return 0.0

    mlu = mean(sentence_lengths)
    normalized_mlu = min(100.0, (mlu / 18.0) * 100.0)

    subordinate_deps = {"advcl", "relcl", "csubj", "acl", "ccomp", "xcomp"}
    subclause_count = sum(1 for token in doc if token.dep_ in subordinate_deps)
    total_words = sum(1 for token in doc if not token.is_punct and not token.is_space)
    subclause_rate = (subclause_count / total_words) * 100.0 if total_words > 0 else 0.0
    normalized_subclause = min(100.0, (subclause_rate / 8.0) * 100.0)

    return _clamp_score((0.5 * normalized_mlu) + (0.5 * normalized_subclause))


def compute_disfluency_rate(word_timestamps: list, transcript: str) -> float:
    if not word_timestamps or len(word_timestamps) < 3:
        return 50.0

    pause_count = 0
    for index in range(len(word_timestamps) - 1):
        current_end = _safe_float(word_timestamps[index].get("end"), 0.0)
        next_start = _safe_float(word_timestamps[index + 1].get("start"), current_end)
        if (next_start - current_end) > 0.5:
            pause_count += 1

    total_duration_seconds = _safe_float(word_timestamps[-1].get("end"), 0.0)
    if total_duration_seconds <= 0:
        total_duration_seconds = 0.01
    total_duration_minutes = total_duration_seconds / 60.0
    pauses_per_minute = pause_count / total_duration_minutes

    normalized_transcript = normalize_transcript(transcript)
    word_tokens = re.findall(r"\b[\w']+\b", normalized_transcript)
    total_word_count = len(word_tokens) if word_tokens else 1

    filler_count = count_filler_words(normalized_transcript)
    filler_rate = (filler_count / total_word_count) * 100.0

    raw_disfluency = (pauses_per_minute * 0.4) + (filler_rate * 0.6)
    return _clamp_score(100.0 - (raw_disfluency * 8.0))


def compute_sentence_completion(word_timestamps: list, transcript: str) -> float:
    utterances = []
    if word_timestamps:
        current_words = []
        for index, word_data in enumerate(word_timestamps):
            word = _clean_word(word_data.get("word"))
            if word:
                current_words.append(word)

            if index < len(word_timestamps) - 1:
                current_end = _safe_float(word_data.get("end"), 0.0)
                next_start = _safe_float(word_timestamps[index + 1].get("start"), current_end)
                if (next_start - current_end) > 1.5 and current_words:
                    utterances.append(" ".join(current_words).strip())
                    current_words = []

        if current_words:
            utterances.append(" ".join(current_words).strip())

    if not utterances and transcript:
        utterances = [sent.text.strip() for sent in _nlp(transcript).sents if sent.text.strip()]

    if not utterances:
        return 70.0

    completed_pos = {"NOUN", "VERB", "ADJ", "ADV", "PROPN"}
    incomplete_pos = {"DET", "ADP", "CCONJ", "SCONJ", "AUX"}

    completed_count = 0
    for utterance in utterances:
        words = re.findall(r"\b[\w']+\b", utterance)
        if len(words) < 3:
            continue

        doc = _nlp(utterance)
        meaningful = [token for token in doc if not token.is_punct and not token.is_space]
        if not meaningful:
            continue

        last_token = meaningful[-1]
        if last_token.pos_ in completed_pos:
            completed_count += 1
        elif last_token.pos_ in incomplete_pos:
            continue
        else:
            completed_count += 1

    if not utterances:
        return 70.0

    return _clamp_score((completed_count / len(utterances)) * 100.0)


def compute_prosodic_confidence(audio_features) -> float:
    if audio_features is None:
        return 60.0

    def get_feature(column_name):
        try:
            if column_name in audio_features.columns:
                return float(audio_features[column_name].iloc[0])
        except Exception:
            logger.warning("Unable to extract feature %s", column_name, exc_info=True)
        return None

    f0_mean = get_feature("F0semitoneFrom27.5Hz_sma3nz_amean")
    f0_stddev_norm = get_feature("F0semitoneFrom27.5Hz_sma3nz_stddevNorm")
    if f0_stddev_norm is None:
        pitch_stability = 60.0
    else:
        pitch_stability = _clamp_score(100.0 - (f0_stddev_norm * 150.0))

    if f0_mean is not None and (f0_mean < 20 or f0_mean > 80):
        pitch_stability = max(0.0, pitch_stability - 8.0)

    loudness_mean = get_feature("loudness_sma3_amean")
    loudness_stddev = get_feature("loudness_sma3_stddevNorm")
    if loudness_stddev is None:
        loudness_confidence = 60.0
    else:
        loudness_confidence = _clamp_score(100.0 - (loudness_stddev * 100.0))

    if loudness_mean is not None and loudness_mean < 0.1:
        loudness_confidence = max(0.0, loudness_confidence - 6.0)

    voiced_segment_mean = get_feature("VoicedSegmentLengthMean")
    if voiced_segment_mean is None:
        speaking_rate_score = 60.0
    else:
        speaking_rate_score = _clamp_score(100.0 - (abs(voiced_segment_mean - 0.45) * 220.0))

    final_score = (
        (0.5 * pitch_stability)
        + (0.3 * loudness_confidence)
        + (0.2 * speaking_rate_score)
    )
    return _clamp_score(final_score)


def compute_recovery_speed(word_timestamps: list) -> tuple[float, float]:
    if not word_timestamps or len(word_timestamps) < 10:
        return 2.0, 80.0

    fillers_single = {
        "um",
        "uh",
        "basically",
        "like",
        "literally",
        "right",
        "actually",
        "honestly",
    }
    filler_phrases = {"you know", "sort of", "kind of", "i mean", "and so"}
    natural_sentence_endings = {
        "that",
        "this",
        "it",
        "so",
        "and",
        "but",
        "because",
        "which",
        "who",
        "when",
        "if",
    }

    recovery_times = []
    freeze_events = 0

    for index in range(len(word_timestamps) - 1):
        current_word_raw = _clean_word(word_timestamps[index].get("word"))
        current_word = current_word_raw.lower().strip("\"'()[]{}")
        current_end = _safe_float(word_timestamps[index].get("end"), 0.0)
        next_start = _safe_float(word_timestamps[index + 1].get("start"), current_end)
        pause_gap = next_start - current_end

        is_natural_end = current_word in natural_sentence_endings or bool(
            re.search(r"[\.!\?,:;]$", current_word_raw)
        )
        if pause_gap <= 1.2 or is_natural_end:
            continue

        freeze_events += 1
        recovery_time = None
        search_deadline = current_end + 5.0

        for candidate_index in range(index + 1, len(word_timestamps) - 2):
            first = word_timestamps[candidate_index]
            second = word_timestamps[candidate_index + 1]
            third = word_timestamps[candidate_index + 2]

            first_start = _safe_float(first.get("start"), 0.0)
            first_end = _safe_float(first.get("end"), first_start)
            second_start = _safe_float(second.get("start"), first_end)
            second_end = _safe_float(second.get("end"), second_start)
            third_start = _safe_float(third.get("start"), second_end)

            if first_start > search_deadline:
                break

            inter_gap_one = second_start - first_end
            inter_gap_two = third_start - second_end

            first_word = _clean_word(first.get("word")).lower()
            second_word = _clean_word(second.get("word")).lower()
            third_word = _clean_word(third.get("word")).lower()
            sequence_text = " ".join([first_word, second_word, third_word])
            has_phrase_filler = any(phrase in sequence_text for phrase in filler_phrases)

            if (
                inter_gap_one < 0.3
                and inter_gap_two < 0.3
                and first_word not in fillers_single
                and second_word not in fillers_single
                and third_word not in fillers_single
                and not has_phrase_filler
            ):
                recovery_time = first_start - current_end
                break

        if recovery_time is None:
            recovery_time = 5.0

        recovery_times.append(max(0.0, recovery_time))

    if freeze_events == 0:
        return 1.5, 90.0

    mean_recovery_seconds = mean(recovery_times) if recovery_times else 5.0
    normalized_score = _clamp_score((1.0 - (mean_recovery_seconds / 5.0)) * 100.0)
    return round(mean_recovery_seconds, 2), round(normalized_score, 2)
