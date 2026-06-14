from app.utils import nlp_helpers


def test_normalize_transcript_removes_noise():
    text = "  Hello, THERE!!!   This is   a test.  "
    normalized = nlp_helpers.normalize_transcript(text)
    assert normalized == "hello there this is a test"


def test_count_filler_words_counts_single_and_phrase_fillers():
    text = "Um I was, you know, basically trying to explain like the issue."
    assert nlp_helpers.count_filler_words(text) == 4


def test_lexical_diversity_rewards_varied_vocabulary():
    repetitive = " ".join(["alpha"] * 60)
    varied = " ".join([f"word{i}" for i in range(60)])

    repetitive_score = nlp_helpers.compute_lexical_diversity(repetitive)
    varied_score = nlp_helpers.compute_lexical_diversity(varied)

    assert 0 <= repetitive_score <= 100
    assert 0 <= varied_score <= 100
    assert varied_score > repetitive_score


def test_syntactic_complexity_returns_scaled_score():
    simple = "I work. You lead. We deliver."
    complex_text = (
        "When the release scope changed overnight, I reorganized the rollout plan, "
        "aligned dependencies with product, and re-sequenced critical tasks so the team could ship safely."
    )

    simple_score = nlp_helpers.compute_syntactic_complexity(simple)
    complex_score = nlp_helpers.compute_syntactic_complexity(complex_text)

    assert 0 <= simple_score <= 100
    assert 0 <= complex_score <= 100
    assert complex_score >= simple_score


def test_disfluency_rate_penalizes_many_pauses_and_fillers():
    smoother_timestamps = [
        {"word": "I", "start": 0.0, "end": 0.2},
        {"word": "spoke", "start": 0.25, "end": 0.45},
        {"word": "clearly", "start": 0.5, "end": 0.8},
        {"word": "today", "start": 0.85, "end": 1.1},
    ]
    disfluent_timestamps = [
        {"word": "Um", "start": 0.0, "end": 0.2},
        {"word": "I", "start": 1.0, "end": 1.2},
        {"word": "was", "start": 2.0, "end": 2.2},
        {"word": "like", "start": 3.2, "end": 3.4},
        {"word": "you", "start": 4.5, "end": 4.7},
        {"word": "know", "start": 4.8, "end": 5.0},
    ]

    smooth_score = nlp_helpers.compute_disfluency_rate(smoother_timestamps, "I spoke clearly today")
    disfluent_score = nlp_helpers.compute_disfluency_rate(
        disfluent_timestamps,
        "Um I was like you know trying",
    )

    assert 0 <= smooth_score <= 100
    assert 0 <= disfluent_score <= 100
    assert smooth_score > disfluent_score


def test_recovery_speed_returns_seconds_and_score_tuple():
    timestamps = [
        {"word": "I", "start": 0.0, "end": 0.2},
        {"word": "need", "start": 0.25, "end": 0.45},
        {"word": "to", "start": 0.5, "end": 0.6},
        {"word": "explain", "start": 0.65, "end": 1.0},
        {"word": "this", "start": 1.05, "end": 1.3},
        {"word": "carefully", "start": 1.35, "end": 1.7},
        {"word": "um", "start": 3.4, "end": 3.5},
        {"word": "so", "start": 3.55, "end": 3.7},
        {"word": "the", "start": 3.75, "end": 3.85},
        {"word": "fix", "start": 3.9, "end": 4.1},
        {"word": "is", "start": 4.15, "end": 4.3},
        {"word": "ready", "start": 4.35, "end": 4.55},
    ]

    seconds, score = nlp_helpers.compute_recovery_speed(timestamps)
    assert isinstance(seconds, float)
    assert isinstance(score, float)
    assert seconds >= 0
    assert 0 <= score <= 100


def test_prosodic_confidence_defaults_when_audio_features_missing():
    score = nlp_helpers.compute_prosodic_confidence(None)
    assert score == 60.0
