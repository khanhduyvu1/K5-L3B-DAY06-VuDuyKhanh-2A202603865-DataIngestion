# Kết quả retrieval (tự động)

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Filter tuân thủ top-3 (n/N) | Câu trượt Hit@3 |
|---|---|---|---|---|---|
| A | dev | 11/18 | 16/18 | 0/6 | q11, q18 |
| A | test | 3/6 | 6/6 | 1/2 | — |
| A | all | 14/24 | 22/24 | 1/8 | q11, q18 |
| B | dev | 14/18 | 17/18 | 0/6 | q18 |
| B | test | 5/6 | 6/6 | 1/2 | — |
| B | all | 19/24 | 23/24 | 1/8 | q18 |
| C | dev | 16/18 | 17/18 | 6/6 | q18 |
| C | test | 6/6 | 6/6 | 2/2 | — |
| C | all | 22/24 | 23/24 | 8/8 | q18 |

| Index | Chunk | Ký tự TB | Max ký tự | Token max | Chunk > 512 token | Chunk nhiều Điều | Embed (s) |
|---|---|---|---|---|---|---|---|
| A | 772 | 496.4 | 499 | 164 | 0 | 451 | 10.82 |
| B | 600 | 595.6 | 1000 | 285 | 0 | 0 | 9.63 |
