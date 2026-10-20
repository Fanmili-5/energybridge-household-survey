> 历史记录，适用范围按原文版本判读。[整理前原文](https://github.com/Fanmili-5/energybridge-household-survey/blob/60e5505d86825593009eaa47de447d67f7825073/docs/submission-flow-v619.md)。当前方法与发布请从[项目首页](../../../README.md)进入。

# Separate submission and feedback completion screens

The confirmation controls previously shared the final optional questionnaire page. After feedback was saved, the browser downloaded the entire simulation result again and displayed only an inline status message, making success difficult to recognize.

UI v6.19 adds a seventh questionnaire step, “确认提交”. The optional questions remain on their own page. Forward/back navigation and the optional-skip button retain entered answers; consent is still explicitly required. The existing image captcha opens from the confirmation step, and successful admission leads to the waiting screen.

A confirmed feedback save now opens a dedicated completion screen immediately, with a button to inspect the saved feedback. Success no longer depends on a subsequent result/history GET. A failed save retains the response and supports an idempotent retry. Historical saved records remain viewable, and opening the website still starts on the questionnaire entry rather than forcing the previous comparison open.

Validation: the disposable browser → HTTP/SQLite → native EnergyPlus with fixed offline planner → decimal feedback → reload test passed at 390px and 1365px. It covers separate confirmation navigation, active consent, captcha, an injected save failure, unchanged score inputs on retry, success without a result GET, completion focus, and saved-feedback retrieval after reload. Two synthetic test cases were stored only in the temporary database; no paid model calls were made. Completion and confirmation screenshots were visually checked at both viewport sizes.

The change does not modify questionnaire fields, EB planning, EnergyPlus execution, scoring schema, or engineering collection mode.
