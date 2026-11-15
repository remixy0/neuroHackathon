# Third-party notices — BrainAccessKit

BrainAccessKit itself is proprietary (see `LICENSE.md`). The distribution zip additionally
redistributes the third-party components below in binary form; each entry reproduces the notice
its licence requires to accompany a binary redistribution. This file ships inside
`dist/BrainAccessKit-<version>.zip` next to `LICENSE.md`.

Components a consumer declares themselves (kotlinx-coroutines, kotlinx-serialization, JNA — all
Apache-2.0, none shipped in the zip) are listed at the end for completeness; they carry no
redistribution-notice obligation on this zip because the zip does not contain them.

---

## liblsl / liblsl-Java — Lab Streaming Layer

Shipped as `libs/liblsl-Java-release.aar`: the Java binding (`edu.ucsd.sccn.LSL`) plus the native
`liblsl.so` for `arm64-v8a`, `armeabi-v7a`, `x86`, `x86_64`. Consumed `compileOnly` by the `:lsl`
module; the aar is the consumer's runtime copy. Licence: **MIT**.

```
Copyright (c) 2012-2024 Christian Kothe, Swartz Center for Computational
Neuroscience, UCSD, and the LSL contributors

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

---

## Nordic Semiconductor Android BLE library — `no.nordicsemi.android:ble{,-ktx}:2.9.0`

`transport-android-release.aar` is compiled against it and exposes its types on the transport's
API surface (the consumer declares the dependency; the aar does not embed it). Licence:
**BSD 3-Clause**.

```
Copyright (c) 2015, Nordic Semiconductor
All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software without
   specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

---

## Declared by the consumer, not shipped in the zip

| Component | Coordinates | Licence |
|---|---|---|
| Kotlin coroutines | `org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0` | Apache-2.0 |
| Kotlin serialization | `org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3` | Apache-2.0 |
| Java Native Access (JNA) — required by liblsl-Java | `net.java.dev.jna:jna:5.14.0@aar` | Apache-2.0 (dual-licensed with LGPL-2.1; taken as Apache-2.0) |

Apps that bundle these in their own APK own the corresponding notices there.
