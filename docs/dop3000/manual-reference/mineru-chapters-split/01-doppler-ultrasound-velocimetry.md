---
title: Chapter 1: Doppler ultrasound velocimetry
manual: DOP3000 Users Manual v6.6.1
pages: 7-12
chapter: 1
extraction_method: mineru
---

# Chapter 1: Doppler ultrasound velocimetry

Doppler ultrasound velocimetry

1 Doppler ultrasound velocimetry

Doppler ultrasound velocimetry, was originally applied in the medical field and dates back more than 30 years. The use of pulsed emissions has extended this technique to other fields and has opened the way to new measuring techniques in fluid dynamics. The term "Doppler ultrasound velocimetry" implies that the velocity is measured by finding the Doppler frequency in the received signal, as is the case in Laser Doppler velocimetry. In fact, in ultrasonic pulsed Doppler velocimetry, this is never the case. Velocities are derived from shifts in positions between pulses, and the Doppler effect plays a minor role.

1.1 Doppler effect

The Doppler effect is the change in frequency of an acoustic or electromagnetic wave resulting from the movement of either the emitter or receptor.

Let us consider an ultrasonic transducer which emits waves of frequency  \( f_{e} \)  and remains constant in a medium where the speed of sound is c. A receptor, or target, in the medium moves with a velocity v. By convention, v is considered negative when the target is moving toward the transducer. If the trajectory of the target forms an angle  \( \theta_{1} \)  with respect to the direction of propagation of the ultrasonic wave, the frequency of the waves perceived by the target will be:

\[
\left| f _ {t} = f _ {e} - \frac {f _ {e} v \cos \theta_ {1}}{c} \right|
\]

Signal Processing S.A. - DOP3000/3010 user's manual

1 - 1

Doppler ultrasound velocimetry

If the acoustic impedance of the target is different from that of the surrounding medium, the waves will be partially reflected. The target acts as a moving source of ultrasonic signals. The frequency of the waves reflected by the target, as measured by a stationary receiver, is:

\[
f _ {r} = f _ {g} + \frac {f _ {g} v \cos \Theta_ {2}}{c}
\]

As the velocity of the target is much smaller than the speed of sound (v << c) it is reasonable to neglect the second order terms. The difference between the emitted and received signals, which is known as the Doppler frequency shift, is then expressed by:

\[
f _ {d} = \frac {f _ {e} v \cdot (\cos \Theta_ {1} - \cos \Theta_ {2})}{c}
\]

If the same transducer is used for receiving the signals the above equation becomes (Doppler equation):

\[
f _ {d} = \frac {2 f _ {e} v \cos {\theta_ {1}}}{c}
\]

1.2 Pulsed Doppler ultrasound

In pulsed Doppler ultrasound, instead of emitting continuous ultrasonic waves, an emitter sends a short ultrasonic burst periodically and a receiver continuously collects echoes issued from targets that may be present in the path of the ultrasonic beam. By sampling the incoming echoes at the same time relative to the emission of the bursts, the shift of positions of scatterers are measured. Let's assume the case illustrated in the figure below, where only one particle is in the ultrasonic beam. From the knowledge of the time delay \( T_{\mathrm{d}} \) between an emitted burst and the echo reflected by the particle, the depth \( p \) of this particle can be computed by:

\[
P = \frac {c \cdot T _ {d}}{2}
\]

where c is the sound velocity of the ultrasonic wave in the liquid.

1 - 2

Signal Processing S.A. - DOP3000/3010 user's manual

Doppler ultrasound velocimetry

If the particle is moving at an angle  \( \theta \)  in relation to the axis of the ultrasonic beam, its velocity can be measured by computing the variation of its depth between two emissions separated in time by  \( T_{prf} \) :

\[
(P _ {2} - P _ {1}) = v \cdot T _ {p r f} \cdot \cos \theta = \frac {c}{2} \cdot (T _ {2} - T _ {1})
\]

The time difference  \( (T_{2}-T_{1}) \)  is always very short, most of the time less than a microsecond. It is advantageous to replace this time measurement by a measurement of the phase shift of the received echo.

\[
\delta = 2 \pi \cdot f _ {e} \cdot (T _ {2} - T _ {1})
\]

where  \( f_{e} \)  is the emitting frequency. With this information the velocity of the target is expressed by:

\[
v = \frac {c \cdot \delta}{4 \pi \cdot f _ {e} \cdot \cos \Theta \cdot T _ {p r f}} = \frac {c \cdot f _ {d}}{2 \cdot f _ {e} \cdot \cos \Theta}
\]

This last equation gives the same result as the Doppler equation but one should always be aware that the phenomena involved are not the same. Let's assume that the particles are randomly distributed inside the ultrasonic beam. The echoes returned by each particle are then combined together in a random fashion, giving a random echo signal. Hopefully, a high degree of correlation exists between different emissions. This high degree of correlation is highlighted in all digital processing techniques used in Signal Processing's Ultrasonic Doppler velocimeter to extract information, such as the velocity.

1.3 Advantages and limitations

The main advantage of pulsed Doppler ultrasound is its ability to offer spatial information associated with velocity values. Unfortunately, as the information is available only

Signal Processing S.A. - DOP3000/3010 user's manual

1 - 3

Doppler ultrasound velocimetry

periodically, this technique suffers from the Nyquist theorem. This means that a maximum velocity exists for each pulse repetition frequency (PRF):

\[
v _ {m a x} = \frac {c}{4 \cdot f _ {e} \cdot \cos \Theta \cdot T _ {p r f}}
\]

If the measured velocity is higher than this maximum velocity, a phenomena named aliasing will appear. In such a situation, all Doppler frequencies above the half of the sampling frequency ( \( f_{prf} = 1/T_{prf} \) ), are folded back in the low frequency region or aliased. The figure below illustrates the relationship between the real frequency and the measured frequency.

At point ①, the real Doppler frequency is below the Nyquist limit ( \( F_{prf}/2 \) ), so the measured frequency is equal to the real frequency. At point ②, the real Doppler frequency is much above the Nyquist limit. Point ② is then backfolded to point ③, which gives a negative velocity. This negative frequency is equal to the real frequency from which the sampling frequency is subtracted. For an analog signal it is possible to avoid aliasing by filtering the signal before sampling it in order to remove all the frequencies above the Nyquist limit ( \( F_{PRF}/2 \) ). Unfortunately for pulsed Doppler ultrasound only samples are available and therefore it is not possible to remove the aliasing. The only solution is to adapt the sampling rate or the pulse repetition frequency to the Doppler signal that has to be measured.

Note: An easy way to check the presence of aliasing is to examine the evolution of the measured Doppler frequency when changing the pulsed repetition frequency.

In addition to the maximum velocity limitation, there is a maximum depth at which a velocity may be measured. This limit is determined by the time needed for the ultrasonic signal to travel from the transducer to the target and back. This time is determined by the

1 - 4

Signal Processing S.A. - DOP3000/3010 user's manual

Doppler ultrasound velocimetry

pulse repetition frequency (PRF) of the ultrasonic pulses. This gives a maximum depth equal to:

\[
P _ {m a x} = \frac {T _ {p r f} \cdot c}{2}
\]

Reducing the PRF (increasing  \( T_{prf} \) ) will increase the maximum measurable depth, but will also reduce the maximum Doppler frequency which can be measured. The maximum velocity and depth which may be measured are thus related according to the following equation:

\[
P _ {m a x} V _ {m a x} = \frac {c ^ {2}}{8 f _ {e}}
\]

At any given instant, an echo signal can come from many different depths, corresponding to echoes from previously emitted signals. The presence of several acoustic interfaces also causes several reflections which can cause a false determination of the target depth. Nevertheless, if the PRF is sufficiently low (a few kHz), the attenuation of previously emitted pulses will render them indiscernible. The same goes for reflected signals. With a large increase in the PRF, pulsed Doppler ultrasound can approach the properties of continuous wave Doppler, with a loss of axial resolution but no maximum velocity limitation.

Signal Processing S.A. - DOP3000/3010 user's manual

1 - 5

Doppler ultrasound velocimetry

1 - 6

Signal Processing S.A. - DOP3000/3010 user's manual