# The ultrasonic demo

One wiring setup, three stages that escalate. Nothing is rebuilt between
them: the transducers stay where they are, and only the flowgraph changes.
That is the point of the demo as much as the ultrasound is -- the M2K is
the whole radio, and everything else is software.

## Wiring

    W1  ---------> TX transducer -----> GND
    RX transducer -> input 1+,  RX other leg -> 1-  tied to GND

Both transducers face each other, a hand's width apart to start. No
amplifier, no matching network, nothing between the board and the parts.

**Direct drive is fine, and here is the arithmetic.** These transducers
are piezo discs: electrically a capacitor of roughly 2 nF, which at
40 kHz is about 2 kOhm. W1 is a 50 Ohm source that swings +/-5 V. Driving
2 kOhm from 50 Ohm costs nothing and draws about 2.5 mA at full swing, so
the generator never notices the load. Nobody needs a driver stage to get
a signal across a table.

**Input range `high`.** That is the +/-2.5 V one -- the name describes
the amplifier, not the volts, which is backwards from how anyone would
guess. One count is worth about 1.5 mV there, which is the smallest step
this demo can see and therefore the thing that decides whether a gain
stage is ever needed.

**The receiver is its own filter.** A 40 kHz transducer is a mechanical
resonator with a bandwidth of a couple of kHz. Everything outside that
band is rejected before it becomes a voltage at all, which is why a raw
transducer straight into an ADC works better than the SNR arithmetic
suggests it should. It is also why stage 1 has to happen first: the
filter's centre frequency is a property of the part in your hand, not of
the number printed on it.

## Stage 1 -- the sweep

`bench/ultrasonic_sweep.py`. Steps W1 across 36-44 kHz, measures what
comes back at each frequency, and reports the peak and the -6 dB
bandwidth.

    python3 bench/ultrasonic_sweep.py
    python3 bench/ultrasonic_sweep.py --start 38000 --stop 42000 --step 50

Everything downstream needs f0, so this runs first whatever else happens.
It is also a demo in its own right, and a short one: the response is a
sharp peak, and the lesson is that "40 kHz" was a marketing number. Two
minutes, no failure mode -- if the transducers are connected at all, a
curve appears.

Run it a second time with the receiver turned to face away, or unplugged.
What is left is electrical crosstalk through the board and the ground
lead, and that floor is what stage 2 has to see past.

## Stage 2 -- time of flight, and the ruler

Send a short burst at f0, capture, find when it arrives, print
centimetres. The transducers face each other; move one, and the number
tracks it.

This is the centrepiece rather than the stretch goal, and the reason is
how it fails. A link either works or shows nothing. A distance readout
degrades gracefully: a weak signal means a shorter maximum range and the
number on screen still follows your hand. In a room of twenty people that
difference matters more than which demo is more sophisticated.

Direct path, not echo. An echo off a hand pays the spreading loss twice
and may not clear the noise at 10 Vpp; two transducers facing each other
have margin to spare. Echo is worth trying once the direct path works,
and is not what the demo depends on.

**Why the numbers are absurdly good.** At 1 MS/s one sample is 343 mm/ms
/ 1000 = 0.343 mm of path. Sample-level timing alone -- no interpolation,
no clever estimator -- resolves a third of a millimetre. That is the
whole lesson in one line: your sample rate is your ruler.

**And why they are not that good.** The speed of sound is
331.3 + 0.606 T m/s, so a room 5 degrees off from your assumption moves
every reading by nearly 1%: about 3 mm at a 30 cm range. The ADC is not
the limit. The air is. A demo that shows both of those in the same minute
is a better teaching artifact than one that only shows the first.

**The blind zone is real.** A resonator with a bandwidth of 2 kHz has a
Q near 20, so it rings for roughly 4.6 * Q / (pi * f0), about 0.7 ms
after the drive stops -- call it 25 cm of path before the receiver has
gone quiet enough to hear anything new. Expect a minimum range, measure
it, and put it in the demo notes rather than discovering it in front of
the room. The exact number comes out of stage 1's ringdown measurement.

## Stage 3 -- the FSK link

`~/USAFA/ECE448/L01_Intro/fsk_project.grc` retuned, as decided on
2026-09-04. 200 baud with 600 Hz deviation fits inside a 2 kHz mechanical
bandwidth with room to spare, which stage 1 confirms rather than assumes.
Endpoints become `analog_sink` at 750 kS/s and `analog_source` at
1 MS/s; the tones move to f0 +/- 300; the xlating filter recentres.

It is the finale because it is the one that can leave nothing on screen.
If stage 2 lands early, this is the payoff. If it does not, the session
still has two working demos.

## What every station needs

One M2K, one transducer pair, two wires. That is the whole bill of
materials, which makes this the only one of the three demos where
hardware scarcity stops being an architecture problem. No instructor
unit, no shared board, no receive-only stations.

## Numbers to get on the bench, in this order

| # | number | what it decides |
| --- | --- | --- |
| 1 | f0 and the -6 dB bandwidth | every frequency downstream, and whether 600 Hz deviation fits |
| 2 | received amplitude vs distance at f0 | the maximum range, and whether a gain stage is ever needed |
| 3 | crosstalk amplitude and duration | how early stage 2 can start looking for an arrival |
| 4 | ringdown time after the drive stops | the blind zone, and the fastest the demo can repeat |

1 and 4 come out of stage 1. 2 is stage 1 run at several distances. 3 is
stage 1 with the receiver turned away.

## Not assumed

- **Differential drive across W1 and W2 is not a free 6 dB.** Doubling
  the drive by putting the transducer between two anti-phase generators
  is the obvious way to get more range, and it may not work here: W1 and
  W2 are separate IIO devices, `m2k-dac-a` and `m2k-dac-b`, so two cyclic
  buffers start independently and their relative phase is not something
  the current blocks control. Whether it is stable across a start is a
  measurement -- capture both on inputs 1 and 2, restart, compare phase --
  and until someone takes it, treat the second generator as unavailable.
- **Whether the direct path needs a gain stage at all.** Measurement 2
  answers it. The board sees about 1.5 mV per count on the `high` range,
  and a resonant receiver at close range should deliver far more than
  that, but "should" is not a number.
- **Whether non-cyclic analog streaming holds at 750 kS/s.** Stage 2 sends
  bursts on demand, which is the same problem the SPI work already hit on
  the digital side. Fall back to a single cyclic buffer if it underruns.
