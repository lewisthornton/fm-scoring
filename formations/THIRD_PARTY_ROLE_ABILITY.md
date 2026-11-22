# Third-party role-ability attribution and permission

Source project: [Napas/fm-mcp](https://github.com/Napas/fm-mcp), Napas and the
project's contributors; original copyright remains with their respective
holders. The pinned source revision is
`4f19a3f0d1130e47d604173a78ff01642f538d52`.

On 2026-11-22 the fm-scoring maintainer reported obtaining permission from
the author. When specifically asked whether the permission covered publishing
a source-derived Python implementation, role-attribute tables and fixtures
in this public MIT-licensed repository, the maintainer supplied the following
grant text. This is recorded as **user-supplied permission**, not as a licence
declared in the upstream repository, and was not independently authenticated
with the author. At the pinned revision no standalone `LICENSE`, `LICENSE.md`
or `COPYING` was found, nor a copyright notice in the inspected role files.
The grant refers to an above copyright notice; no separate exact notice was
supplied. Retain the attribution above and include any original notice supplied
by the rights holder. Do not infer ownership of third-party game material.

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

On the maintainer's representation, the grant permits the source-derived port,
classifier tables and associated upstream synthetic reference fixture in this
PR. It does not establish that fm-mcp itself is MIT-licensed, give rights to
game binaries, private saves, third-party datasets or trademarks, or certify
that any reconstruction is numerically identical to the game. No game assets,
private data or real-player fixtures are redistributed. If the scope or
authorship of the grant is challenged, stop further distribution pending review.

Adapted material and pin:

- [roleability.go](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/internal/fm/roleability.go)
  and [oopability.go](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/internal/fm/oopability.go): numerical algorithms, masks and thresholds.
- [roletables.go](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/internal/fm/roletables.go)
  and [tacticnames.go](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/internal/savefile/tacticnames.go): classifier lists, role identifiers/names and positional masks.
- [player.go](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/internal/savefile/player.go): ordering of raw fields in reference fixture.
- [role-ability.md](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/docs/format/role-ability.md): build findings and context restrictions.
- [roleability_test.go](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/internal/fm/roleability_test.go),
  [oopability_test.go](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/internal/fm/oopability_test.go),
  [role_ability_golden.txt](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/internal/fm/testdata/role_ability_golden.txt): author-published invented numerical cases; no real-save tests copied or run.

The Python port, TOML representation and test adaptation refer back to this
notice. The fm-scoring project licence is unchanged.
