# extract-service-template — Archive Summary

- **Archived**: 2026-10-18
- **Original Created**: 2026-10-18
- **Quality Grade**: A
- **Plan Decision**: option-a (graded_by: human)

## User Story

Python 後端開發者可在 repo 外產生空服務，以自己的 lock／venv 安裝 kernel、維護 migrations 並操作 API／consumer／worker。每個 microservice 各自一個 repo；外層 runtime、工具與測試可直接客製化，選擇更新時合併修改並處理衝突。框架維護者由 CI 驗證 template／example 漂移與既有行為保留。

## Affected Modules

| Module | Impact | Description |
|---|---|---|
| template | High | Copier 骨架、三來源、開發工具／容器、更新與 framework-only 歷史 ownership 漂移檢查 |
| example | High | workspace answers、通用 runtime 測試與 repo-only 產物驗收；保留 billing 與既有 migration chain |
| kernel | Low | wheel 分發測試；不修改 runtime API |

## Requirements

| REQ ID | Status | Description |
|---|---|---|
| REQ-TEMPLATE-001 | ADDED | 可獨立驗收的空服務產生 |
| REQ-TEMPLATE-002 | ADDED | 空服務 schema 生命週期 |
| REQ-TEMPLATE-003 | ADDED | 可分發的三角色 runtime |
| REQ-TEMPLATE-004 | ADDED | 骨架更新與服務內容保護 |
| REQ-TEMPLATE-005 | ADDED | 可持續更新的品質基準 |
| REQ-TEMPLATE-006 | ADDED | 參考服務骨架漂移與退役副本偵測 |
| REQ-TEMPLATE-007 | ADDED | 完整產物驗收與既有行為保留 |

MODIFIED／REMOVED 均無；原 kernel、wire、交易、lifecycle 與 example 業務維持 regression。

## Completion

- **Tasks**: 27/27 code（100%）；1/1 verification、0 manual。
- **Acceptance Criteria**: fresh grader 核對 19/19 frozen scenarios、7/7 REQ；CLI 保留 late-capture 歷史限制，spec 維度最終為 not-adjudicated。

## Review & Verify

- **Review**: 2 rounds，2 critical／1 major，三項均 fixed，無未解 findings。修正 snapshot symlink 重定位／來源保護、template 上游刪檔的舊 example 副本 false-green、worker health route oracle；兩項 critical 先獨立確認，皆有 fail-then-pass／mutation pins，ownership 架構補強經使用者核准。
- **Verify**: Grade A、result PASS、status verified。tasks／Knowledge／tests machine PASS，Constitution fresh-context 6/6 PASS，design 不適用；spec 的 7/7 現況判定符合，CLI 因 acceptance revision 2 在 plan 修訂而記 not-adjudicated，未改寫 baseline。
- **Tests**: Python 3.13.12／pytest 9.1.1，正式 `make check` attempt cb0cc044-f821-47eb-ad3f-a041841ef5c9、exit 0；kernel332/332、example270/270、git／path 各50/50，全部零 skip／failure／error。line+branch coverage 分別2548/2688=94.7917%、815/825=98.7879%、兩產物各226/234=96.5812%；產物各13/13 app files、0 excluded。lock／format／lint／typing／package checks、11/11 import contracts、實際三角色程序／容器、migration、更新／衝突、drift 全通過。
- **Preservation**: 原 Phase 1 kernel331/331、example126/126 保留；47 runtime case mappings 保留。template／example 四個 runtime 主檔共8/8與 HEAD 25a83a9 位元組相同。
- **Quality Log**: plan 的早期 FLAWS 為缺少空服務獨立 coverage 與相對來源／dirty oracle，後續原型與正式驗收補齊、Architecture Verifier PASS；tasks 保留28項 sizing advisory；最終 verify WARN 為 acceptance baseline late-capture。未清除歷史 FAIL／WARN，沒有未解 critical 或人工 override。
- **Evidence**: 完整 bundle 保存 review／verify receipts、當前 JUnit／coverage、scenario 對照與 mutation logs；review／tests 最終有效輸入 digest 同為 ea3ec7202a1186767b11ef57c1df89d21b9fca066d7744939d7183bc79bf9c74。

## Knowledge Update

example／kernel／template 三個 README 與 module map 已在最終 review／tests／verify 前同步並 stamp。框架 ownership 不進下游服務；下游升級使用 Copier update，recopy 僅供框架同步／隔離驗收。原始機器掃描與 lessons checkpoint 於 archive 後重新確認。

## Limitations

Grade A 的 late-capture 是歷史基準限制，不代表當前七項 REQ 失敗；不宣稱 Grade S。git 固定版本與 Docker 流程使用本機測試 tag／唯讀 loopback endpoint，未發布正式 kernel tag；path lock 僅供本機開發。下游更新仍需 Git checkpoint、檢視衝突與服務自己的完整驗證。
