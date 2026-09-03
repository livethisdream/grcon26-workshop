# gr-iio's device_sink can only drive one bit-field channel

Found 2026-09-02 on an ADALM2000 (Rev.D Z7010, fw v0.33) with
GNU Radio 3.10.9.2. It costs us `digital_sink`, which no longer uses
`iio.device_sink` at all. Written down in full because the failure is
silent: the block reports success and the pins simply never move.

## What happens

Send four different square waves to four DIO pins through one
`iio.device_sink`. Three pins stay flat. The fourth — always the
highest-numbered one — carries its stream perfectly.

No error, no warning, no dropped-sample count. The flowgraph looks
healthy.

## Why

The M2K's sixteen logic-analyzer channels are not sixteen samples side
by side. They are sixteen **1-bit fields inside one 16-bit word**, each
at a shift equal to its pin number:

```
voltage0   length=16  bits=1  shift=0
voltage1   length=16  bits=1  shift=1
...
voltage15  length=16  bits=1  shift=15
```

libiio models this correctly. `iio_buffer_step` is 2 bytes whether you
enable one channel or all sixteen, and `iio_buffer_first` returns the
**same address** for every one of them.

`device_sink_impl::work` then does this
(`gr-iio/lib/device_sink_impl.cc`):

```c
for (unsigned int i = 0; i < input_items.size(); i++)
    channel_write(channel_list[i], input_items[i], noutput_items * sizeof(short));
```

and `channel_write` walks the buffer calling:

```c
iio_channel_convert_inverse(chn, (void*)dst_ptr, (const void*)src_ptr);
```

`iio_channel_convert_inverse` is a **full-width store**, not a
read-modify-write. It writes all `length` bytes — 2 here — so it plants
its own bit and zeroes every other bit in the word. Channel `i+1`
therefore erases channel `i`, and only the last channel in the list
survives.

## Reproduction, at the libiio level

No GNU Radio needed. Two channels of one device, written in turn:

```python
import iio, array
ctx = iio.Context("ip:192.168.2.1")
d = ctx.find_device("m2k-logic-analyzer-tx")
c0, c1 = d.find_channel("voltage0", True), d.find_channel("voltage1", True)
for c in d.channels:
    c.enabled = False
c0.enabled = c1.enabled = True
b = iio.Buffer(d, 4, False)

c0.write(b, bytearray(array.array('h', [1, 1, 1, 1]).tobytes()))
print(bytes(b.read()).hex())      # 0100010001000100  -- bit 0 set
c1.write(b, bytearray(array.array('h', [0, 0, 0, 0]).tobytes()))
print(bytes(b.read()).hex())      # 0000000000000000  -- bit 0 GONE
c1.write(b, bytearray(array.array('h', [1, 1, 1, 1]).tobytes()))
print(bytes(b.read()).hex())      # 0200020002000200  -- still gone
```

## Reproduction, on the wire

Jumper `DIO0-DIO4`, `DIO1-DIO5`, `DIO2-DIO6`. Drive a square wave into
exactly one input port of a multi-pin sink and constant zero into the
rest, then count the ones captured on the other side:

| sink pins | square on port | DIO0 | DIO1 | DIO2 |
| --- | --- | --- | --- | --- |
| 1 | 0 | **227** | – | – |
| 2 | 0 | 0 | 0 | – |
| 2 | 1 | 0 | **212** | – |
| 3 | 2 | 0 | 0 | **272** |

Only the last port ever reaches a pin.

The same jumpers driven statically through `raw` on
`m2k-logic-analyzer` track perfectly, which is what rules out the bench
rather than the block.

## The source side is fine

Reading is the mirror image and libiio's demux handles it correctly.
Driving `1 0 1` on DIO0-2 through `raw` and reading four ports of an
`iio.device_source` returns `1 0 1` plus a floating high on the unwired
fourth pin. `digital_source` is still plain gr-iio.

## What we do instead

`_packed_sink` in `gr-m2k/m2k_blocks/digital.py`. `Buffer.write` copies
raw bytes and never calls `convert_inverse`, so we pack the 16-bit word
ourselves — one bit per pin, at the shift the hardware gave that channel
— and push that. Confirmed driving three pins simultaneously, and the
SPI loopback in section 9 of the bench checklist is built on it.

The cost is Python in the path of every buffer. At 1 MS/s with a
16384-sample buffer that is 61 pushes a second, which is fine; 100 MS/s
would be 6100 and would not keep up.

## If this ever goes upstream

The fix is for `channel_write` to read-modify-write when a channel is
narrower than its storage — mask out the field, or memset the buffer
once per work call before the per-channel loop and OR each field in.
Note `work` already memsets the whole buffer, but only when
`interpolation >= 1`, so the zeroing that would make an OR-based fix
safe is not there in the general case.

Worth checking before filing whether any other IIO device exposes
overlapping bit-field scan elements, because the fix should be about
`length != bits`, not about the M2K.
