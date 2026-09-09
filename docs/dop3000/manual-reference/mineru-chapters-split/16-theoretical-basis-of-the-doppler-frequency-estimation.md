---
title: Chapter 16: Theoretical basis of the Doppler frequency estimation
manual: DOP3000 Users Manual v6.6.1
pages: 105-106
chapter: 16
extraction_method: mineru
---

# Chapter 16: Theoretical basis of the Doppler frequency estimation

Theoretical basis of the Doppler frequency estimation

16 Theoretical basis of the Doppler frequency estimation

The amplitudes of the echoes reflected by the particles within the flowing fluid are somewhat random in nature, corresponding to the random distribution of the particles in the fluid medium. Thus, the Doppler signals may be treated as random processes, and characterized by different moments. In order to be able to determine the probability of occurrence of this process, one must have access to a great number of actual occurrences of the process. In practice, it is difficult to obtain measurements of the exact same process under the exact same conditions at several different times. Therefore, a temporal average is preferable to an ensemble average. The temporal average and the ensemble average will not be the same unless the process is stationary and the analysis time is very long (tending to infinity). Considering the Doppler process as stationary, the average frequency may be expressed as the normalized first moment, or:

\[
\begin{array}{c} \hline \mu_ {1} = \bar {f} = \frac {\int_ {- \infty} ^ {\infty} f S (f) d f}{\int_ {- \infty} ^ {\infty} S (f) d f} \\ \hline \end{array}
\]

where  \( S(f) \)  is the spectral density or probability density of the Doppler signal.

The Doppler frequency calculation algorithm is based on the fact that the inverse Fourier transform of the probability density of a stationary process is equal to the auto-correlation function [3]. The first moment \(\mu_{1}\) may be expressed in terms of the time derivatives of the auto-correlation function at the origin:

\[
\dot {f} = \frac {1}{j 2 \pi} \frac {\frac {d}{d t} R (0)}{R (0)}
\]

The auto-correlation function is estimated using the complex envelope of the echo signal.

Signal Processing S.A. - DOP3000/3010 user's manual

16 - 1

Theoretical basis of the Doppler frequency estimation

16 - 2

Signal Processing S.A. - DOP3000/3010 user's manual