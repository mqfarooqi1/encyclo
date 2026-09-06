-- 0004_learning: quizzes and guided learning paths.
-- Every question must cite the article (and ideally the source) that supports its
-- answer, so a quiz can never assert something the encyclopaedia does not.

CREATE TABLE quiz (
    id          INTEGER PRIMARY KEY,
    key         TEXT    NOT NULL UNIQUE,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    article_id  INTEGER REFERENCES article(id) ON DELETE CASCADE,
    category_id INTEGER REFERENCES category(id) ON DELETE SET NULL,
    age_band    TEXT    NOT NULL DEFAULT 'age9_12'
                  CHECK (age_band IN ('age6_8','age9_12','teen','adult')),
    difficulty  TEXT    NOT NULL DEFAULT 'medium'
                  CHECK (difficulty IN ('easy','medium','hard','expert'))
);
CREATE INDEX idx_quiz_article  ON quiz(article_id);
CREATE INDEX idx_quiz_category ON quiz(category_id, age_band);

CREATE TABLE quiz_question (
    id          INTEGER PRIMARY KEY,
    quiz_id     INTEGER NOT NULL REFERENCES quiz(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL DEFAULT 'multiple_choice'
                  CHECK (kind IN ('multiple_choice','true_false','matching','image_id',
                                  'ordering','timeline','map')),
    prompt      TEXT    NOT NULL,
    -- Required by the content validator: a question with no explanation is rejected.
    explanation TEXT    NOT NULL,
    difficulty  TEXT    NOT NULL DEFAULT 'medium'
                  CHECK (difficulty IN ('easy','medium','hard','expert')),
    -- Grounding: which article and source back this answer.
    article_id  INTEGER REFERENCES article(id) ON DELETE SET NULL,
    source_id   INTEGER REFERENCES source(id) ON DELETE SET NULL,
    media_id    INTEGER REFERENCES media(id) ON DELETE SET NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_question_quiz ON quiz_question(quiz_id, sort_order);

CREATE TABLE quiz_option (
    id          INTEGER PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES quiz_question(id) ON DELETE CASCADE,
    text        TEXT    NOT NULL,
    is_correct  INTEGER NOT NULL DEFAULT 0 CHECK (is_correct IN (0, 1)),
    match_key   TEXT,     -- for matching / ordering question kinds
    sort_order  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_option_question ON quiz_option(question_id, sort_order);

CREATE TABLE learning_path (
    id          INTEGER PRIMARY KEY,
    key         TEXT    NOT NULL UNIQUE,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    icon        TEXT,
    age_band    TEXT    NOT NULL DEFAULT 'age9_12'
                  CHECK (age_band IN ('age6_8','age9_12','teen','adult')),
    category_id INTEGER REFERENCES category(id) ON DELETE SET NULL,
    is_builtin  INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0, 1))
);

CREATE TABLE learning_path_step (
    id         INTEGER PRIMARY KEY,
    path_id    INTEGER NOT NULL REFERENCES learning_path(id) ON DELETE CASCADE,
    article_id INTEGER NOT NULL REFERENCES article(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL,
    note       TEXT,
    quiz_id    INTEGER REFERENCES quiz(id) ON DELETE SET NULL,
    UNIQUE (path_id, sort_order)
);
