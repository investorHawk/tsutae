# つたえ フロントエンド

React 18 + Vite 5 + TypeScript（strict）+ react-router-dom 6。テストは vitest + Testing Library（jsdom）。
契約は `docs/architecture.md` §8（API）・§9（フロント）、画面は `docs/spec.md` 3節。

## 確認コマンド（frontend/ で）

```sh
npx vitest run
npx tsc -p tsconfig.app.json --noEmit
npx prettier --check "src/**/*.{ts,tsx,css}"
```

## 約束

- 患者画面の文字列は `usePatientStrings().t(key)` からだけ出す（キーは `backend/tsutae/patient_strings.json`）。質問文は API の `questions[].text`、P2 の質問文は `answers[].question_text`（null なら `history.previous_question`）。患者画面に AI の文は出さない。
- API の 2xx 応答は実行時に形を検査する（患者側は `src/api/patientGuards.ts`、医師側は `src/components/doctor/guards.ts`、部品は `src/api/validate.ts`）。合わなければ `ApiError(200, "invalid_response")` にし、患者画面は `error.generic`、医師画面は code つきの失敗を出す。
- 描画中の例外は `ErrorBoundary` で受け止める（患者側は `PatientLayout`、医師側は `DoctorLayout` と `DoctorShell`）。患者側は `error.generic` だけを出す。
- Skill 変更の差分が空（空白だけを含む）なら失敗として扱い、承認させない。
- `Course.note` は200字まで（code point で数える。schemas.py の `max_length=200` と同じ）。

## 患者画面の直書き検査と、その限界

`src/test/patientTextLint.ts` が TypeScript の構文木で患者のファイルを検査する（テストは `src/test/patientNoHardcodedText.test.ts` と `src/components/patient/noHardcodedText.test.ts`）。

- 契約の2規則: 文字列リテラルに日本語を含めない（`non-ascii`）、JSX のテキストに英字を書かない（`jsx-text`）
- 追加の規則: JSX の子として描かれる位置の英字（`jsx-literal`）、読み上げ・表示される属性の英字（`jsx-attr`）、英単語が2つ以上並ぶ文字列（`ascii-prose`）

**既知の限界**: 1語の英字を変数に入れてから描くもの（`const label = "Advice"; <p>{label}</p>`）は見逃す。契約（§9 W2b の決定）で「変数経由の英字は検査の外」としている。レビューで見る。
