/* The quiz engine.

   One runner drives both standalone quizzes and Explorer Trail stations, so a
   question type only has to be implemented once. Marking happens locally — the
   app must work with no network — and the explanation is always shown, whether
   the answer was right or wrong. Getting it right and not learning why is a
   missed opportunity, not a success. */

import { el, clear } from './dom.js';

const shuffle = (items) => {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
};

/**
 * @param {object} quiz  the quiz payload from /api/quiz/{key}
 * @param {object} opts  { onFinish(score, total), subtitle }
 */
export function quizRunner(quiz, { onFinish, subtitle } = {}) {
  const root = el('div', { class: 'quiz-shell' });
  const questions = quiz.questions || [];
  let index = 0;
  let score = 0;
  const marks = [];        // true | false per answered question

  const progress = () => {
    const bar = el('div', { class: 'qprogress', 'aria-hidden': 'true' });
    questions.forEach((_, i) => {
      const cls = i < marks.length ? (marks[i] ? 'done' : 'wrong') : (i === index ? 'now' : '');
      bar.append(el('i', { class: cls }));
    });
    return bar;
  };

  const finish = () => {
    clear(root);
    const perfect = score === questions.length;
    const passed = score / questions.length >= 0.5;
    root.append(el('div', { class: 'quiz-card', style: { textAlign: 'center' } },
      el('div', { style: { fontSize: '52px', lineHeight: '1' } },
        perfect ? '🏆' : passed ? '🎉' : '📚'),
      el('h2', { style: { fontSize: '27px', margin: '10px 0 6px' } },
        perfect ? 'Every single one!' : passed ? 'Well done' : 'Good try'),
      el('p', { style: { fontSize: '18px', color: 'var(--ink-2)' } },
        `You scored ${score} out of ${questions.length}.`),
      !passed && el('p', { style: { fontSize: '14px', color: 'var(--ink-3)' } },
        'Have another go — you can read the articles first if you like.'),
      el('div', { style: { display: 'flex', gap: '10px', justifyContent: 'center', marginTop: '20px', flexWrap: 'wrap' } },
        el('button', {
          class: 'btn ghost',
          onclick: () => { index = 0; score = 0; marks.length = 0; render(); },
        }, 'Play again'),
      ),
    ));
    onFinish?.(score, questions.length);
  };

  /* -- answer surfaces, one per question kind ------------------------------ */

  function multipleChoice(question, card, done) {
    const buttons = [];
    for (const option of shuffle(question.options)) {
      const button = el('button', { class: 'opt', type: 'button' }, option.text);
      button.addEventListener('click', () => {
        for (const other of buttons) other.disabled = true;
        const right = Boolean(option.is_correct);
        button.classList.add(right ? 'correct' : 'wrong');
        button.append(el('span', { class: 'tick' }, right ? '✓' : '✕'));
        if (!right) {
          for (const other of buttons) {
            if (other.dataset.correct === '1') {
              other.classList.add('correct');
              other.append(el('span', { class: 'tick' }, '✓'));
            }
          }
        }
        done(right);
      });
      button.dataset.correct = option.is_correct ? '1' : '0';
      buttons.push(button);
      card.append(button);
    }
  }

  function ordering(question, card, done) {
    // sort_order holds the correct sequence; the pool is shuffled.
    const correct = [...question.options].sort((a, b) => a.sort_order - b.sort_order);
    const placed = [];
    const slots = el('div', { class: 'order-slots' });
    const pool = el('div', { class: 'order-pool' });
    const check = el('button', { class: 'btn', disabled: true, style: { marginTop: '14px' } },
      'Check my order');

    const redraw = () => {
      clear(slots); clear(pool);
      placed.forEach((option, position) => {
        slots.append(el('button', {
          class: 'order-item', type: 'button',
          onclick: () => { placed.splice(position, 1); redraw(); },
        }, el('span', { class: 'num' }, String(position + 1)), option.text));
      });
      for (const option of poolItems()) {
        pool.append(el('button', {
          class: 'order-item', type: 'button',
          onclick: () => { placed.push(option); redraw(); },
        }, el('span', { class: 'num' }, '+'), option.text));
      }
      check.disabled = placed.length !== question.options.length;
    };
    const shuffled = shuffle(question.options);
    const poolItems = () => shuffled.filter((o) => !placed.includes(o));

    check.addEventListener('click', () => {
      const right = placed.every((option, i) => option.text === correct[i].text);
      clear(slots);
      placed.forEach((option, i) => {
        const ok = option.text === correct[i].text;
        slots.append(el('div', { class: `order-item ${ok ? 'correct' : 'wrong'}` },
          el('span', { class: 'num' }, String(i + 1)), option.text,
          el('span', { class: 'tick' }, ok ? '✓' : '✕')));
      });
      if (!right) {
        slots.append(el('div', { class: 'order-hint', style: { marginTop: '10px' } },
          `The right order is: ${correct.map((o) => o.text).join(' → ')}`));
      }
      check.remove();
      clear(pool);
      done(right);
    });

    card.append(el('p', { class: 'order-hint' }, 'Tap them in order. Tap again to take one back.'),
      slots, pool, check);
    redraw();
  }

  function matching(question, card, done) {
    const lefts = question.options;
    const rights = shuffle(question.options.map((o) => o.match_key));
    const pairs = new Map();          // left text -> right text
    let picked = null;

    const leftCol = el('div', { class: 'match-col' });
    const rightCol = el('div', { class: 'match-col' });
    const check = el('button', { class: 'btn', disabled: true, style: { marginTop: '14px' } },
      'Check my pairs');

    const redraw = () => {
      clear(leftCol); clear(rightCol);
      lefts.forEach((option) => {
        const paired = pairs.get(option.text);
        const cls = picked === option.text ? 'picked' : paired ? 'paired' : '';
        leftCol.append(el('button', {
          class: `match-item ${cls}`, type: 'button',
          onclick: () => {
            if (paired) { pairs.delete(option.text); picked = null; }
            else picked = picked === option.text ? null : option.text;
            redraw();
          },
        }, option.text,
           paired && el('span', { class: 'pairnum' }, `${[...pairs.keys()].indexOf(option.text) + 1}`)));
      });
      rights.forEach((text) => {
        const takenBy = [...pairs.entries()].find(([, v]) => v === text);
        rightCol.append(el('button', {
          class: `match-item ${takenBy ? 'paired' : ''}`, type: 'button',
          onclick: () => {
            if (takenBy) { pairs.delete(takenBy[0]); redraw(); return; }
            if (!picked) return;
            pairs.set(picked, text);
            picked = null;
            redraw();
          },
        }, text));
      });
      check.disabled = pairs.size !== lefts.length;
    };

    check.addEventListener('click', () => {
      let correctCount = 0;
      clear(leftCol); clear(rightCol);
      for (const option of lefts) {
        const chosen = pairs.get(option.text);
        const ok = chosen === option.match_key;
        if (ok) correctCount += 1;
        leftCol.append(el('div', { class: `match-item ${ok ? 'correct' : 'wrong'}` }, option.text));
        rightCol.append(el('div', { class: `match-item ${ok ? 'correct' : 'wrong'}` },
          ok ? chosen : option.match_key,
          !ok && el('span', { class: 'pairnum' }, 'correct answer')));
      }
      check.remove();
      done(correctCount === lefts.length);
    });

    card.append(el('p', { class: 'order-hint' }, 'Tap one on the left, then its partner on the right.'),
      el('div', { class: 'match-grid' }, leftCol, rightCol), check);
    redraw();
  }

  const SURFACES = {
    multiple_choice: multipleChoice,
    true_false: multipleChoice,
    image_id: multipleChoice,
    ordering,
    timeline: ordering,
    matching,
  };

  /* -- the loop ------------------------------------------------------------ */

  function render() {
    clear(root);
    if (index >= questions.length) return finish();

    const question = questions[index];
    root.append(
      el('h1', { style: { fontSize: '26px', marginBottom: '3px' } }, quiz.title),
      subtitle && el('p', { style: { color: 'var(--ink-3)', fontSize: '13.5px', marginBottom: '14px' } },
        subtitle),
      progress(),
    );

    const card = el('div', { class: 'quiz-card' },
      el('div', { class: 'quiz-progress' },
        `Question ${index + 1} of ${questions.length}`,
        question.difficulty ? ` · ${question.difficulty}` : ''),
      el('h2', { class: 'quiz-q' }, question.prompt),
    );
    root.append(card);

    const done = (right) => {
      marks[index] = right;
      if (right) score += 1;
      card.append(el('div', { class: 'explain' },
        el('strong', {}, right ? 'Correct. ' : 'Not quite. '), question.explanation));
      if (question.article_slug) {
        card.append(el('p', { style: { marginTop: '10px', fontSize: '13.5px' } },
          'Read more: ',
          el('a', { href: `#/article/${question.article_slug}`, 'data-link': '' },
            question.article_slug.replace(/-/g, ' '))));
      }
      const next = el('button', { class: 'btn', style: { marginTop: '16px' },
        onclick: () => { index += 1; render(); } },
        index + 1 < questions.length ? 'Next question →' : 'See how I did');
      card.append(next);
      next.focus({ preventScroll: true });
    };

    (SURFACES[question.kind] || multipleChoice)(question, card, done);
  }

  render();
  return root;
}
