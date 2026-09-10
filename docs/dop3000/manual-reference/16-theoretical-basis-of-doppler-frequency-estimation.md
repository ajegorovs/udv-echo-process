# 16. Theoretical basis of the Doppler frequency estimation

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 105-106.

---

<!-- source-pdf-page: 105 -->
## Source PDF page 105

## 16 Theoretical basis of the Doppler frequency estimation

The amplitudes of the echoes reflected by the particles within the flowing fluid are somewhat random in nature, corresponding to the random distribution of the particles in the fluid medium. Thus, the Doppler signals may be treated as random processes, and characterized by different moments. In order to be able to determine the probability of occurrence of this process, one must have access to a great number of actual occurrences of the process. In practice, it is difficult to obtain measurements of the exact same process under the exact same conditions at several different times. Therefore, a temporal average is preferable to an ensemble average. The temporal average and the ensemble average will not be the same unless the process is stationary and the analysis time is very long (tending to infinity). Considering the Doppler process as stationary, the average frequency may be expressed as the normalized first moment, or:

∞

where S(f) is the spectral density or probability density of the Doppler signal.

The Doppler frequency calculation algorithm is based on the fact that the inverse Fourier transform of the probability density of a stationary process is equal to the auto-correlation function [3]. The first moment μ1 may be expressed in terms of the time derivatives of the auto-correlation function at the origin:

The auto-correlation function is estimated using the complex envelope of the echo signal.

#### Equations reconstructed from the page image

*Normalized first spectral moment:*



$$
\mu_1=\bar f=\frac{\int_{-\infty}^{\infty}fS(f)\,df}{\int_{-\infty}^{\infty}S(f)\,df}
$$

*First moment from the autocorrelation derivative:*



$$
\bar f=\frac{1}{j2\pi}\,\frac{\left.\frac{dR}{dt}\right|_{t=0}}{R(0)}
$$

---

<!-- source-pdf-page: 106 -->
## Source PDF page 106
