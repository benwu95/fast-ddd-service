# Development Tools
> 檢查 Python package 覆蓋並產生服務錯誤目錄。

<!-- prospec:module-readme-format 2026-09-01 -->
<!-- prospec:auto-start -->
## Key Files
| File | Purpose |
|------|---------|
| `kernel/src/fast_ddd_devtools/check_packages.py` | Import-linter 設定覆蓋檢查 |
| `kernel/src/fast_ddd_devtools/error_catalog.py` | DomainError 與 aggregate 錯誤目錄 |
| `kernel/pyproject.toml` | CLI entry points 與品質工具設定 |

## Public API
- `find_problems(config, source_root)` — 列出 package 或 wildcard 覆蓋問題。
- `build_catalog()` — 產生已載入類別的穩定錯誤 metadata。
- `fast-ddd-check-packages`、`fast-ddd-error-catalog` — 命令列入口。

## Dependencies
**Depends on:** 無內部 module；error catalog 讀 kernel core 類別與註冊表。
**Used by:** kernel／`example` Makefile；runtime 不可依賴此 package。

## Modification Guide
1. 修改 package discovery → check_packages → temporary package-tree 測試。
2. 新增錯誤 metadata → error_catalog → `kernel/tests/port/test_settings_and_catalog.py`。
3. 修改輸出 → example 的 `make error-catalog` 與 catalog 測試。

## Pitfalls
- 產生目錄前必須 import 服務的 domain／wiring，否則 subclass 尚未註冊。
- 通過 import-linter 不代表空 package 的漏管可忽略；覆蓋工具是獨立檢查。
- 缺 `__init__.py` 的判斷以含 `.py` 的目錄及其祖先推導，涵蓋只含子 package 的中介目錄；與 grimp 一樣跟隨 symlink 目錄，並以實際路徑祖先鏈剪除迴圈；無法列出內容的目錄直接拋錯；root package 第二層以下、目標無法 stat（例如其上層目錄沒有搜尋權限）的 symlink 會被走訪當成檔案而略過，grimp 同樣略過，屬已知限制。排除只看 root package 以下的目錄名稱（`__pycache__`、`.` 開頭），不可改看絕對路徑，否則位於隱藏目錄或以 `..` 傳入的 source root 會整樹略過。
<!-- prospec:auto-end -->
<!-- prospec:user-start -->
<!-- prospec:user-end -->
