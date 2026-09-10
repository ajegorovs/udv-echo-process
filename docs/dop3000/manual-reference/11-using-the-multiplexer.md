# 11. Using the multiplexer

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 81-84.

---

<!-- source-pdf-page: 81 -->
## Source PDF page 81

## 11 Using the multiplexer

The DOP3010 contains 10 channels which are all independent of each other. Each channel has its own BNC connector and its own collection of functioning parameters.

When the multiplexer is enabled, the acquisition of data profiles follows the procedure described below:

- the DOP3010 selects the first channel, which can be any one of the 10 available channels; - it acquires a user's defined number of profiles; - it switches then to the next selected channel; - it repeats this acquisition procedure until the last channel is measured; - if more than one acquisition sequence has been programmed, UDOP closes the current sequence by closing the current block, and starts a new sequence by selecting again the first selected channel. - when the last sequence ends, UDOP can: stops the acquisition process and store the measured data or roll over the measured data, and therefore replace the measured profiles by new ones, repeating all the previous sequences.

Before enabling the multiplexer, the functioning parameters of all the channels that will be used must be defined. These parameters are defined the same way as in non multiplexing mode. Simply select the channel and define the parameters and the type of data that must be measured.

### 11.1 To select a channel:

- enter in the menu "Channels";
- be sure that "Use only channel" is checked;
- point the channel that must be selected and click, like in the figure below:

**Note:** UDOP allows to copy all the parameters from one channel to an other channel. To do this:

#### Figures and in-context visual analysis

**Reconstructed caption:** Single-channel selector.



**In context:** Choosing 'Use only channel' bypasses multiplexed acquisition and routes measurement through one selected front-panel channel.

---

<!-- source-pdf-page: 82 -->
## Source PDF page 82

-select the channel that must be defined (6) -select the channel that contains the parameters that must be applied to the current channel (3); -click the button labeled "Apply parameters from channel"

### 11.2 Enabling the multiplexer

Before enabling the multiplexer you must:

- define the channels that will be included in the multiplexing acquisition. To do this, check the box which corresponds to the number of the channel as displayed in the figure below:

(a cross indicates that the channel will not be included)

- define the channels that will be used as the first channel in the sequence. To do this:

- define the number of times the multiplexing sequence will be repeated:

-        define if the external trigger mode must be used or not;

#### Figures and in-context visual analysis

**Reconstructed caption:** Copy parameters and acquire from another channel.



**In context:** The dialog lets the current channel inherit another channel's setup, reducing inconsistent multiplexer configurations.

**Reconstructed caption:** Enabled-channel sequence.



**In context:** The row of channel toggles defines which channels participate in a multiplexed acquisition cycle.

**Reconstructed caption:** Sequence start-channel selector.



**In context:** Selecting the first channel controls where each multiplexing cycle begins, which matters when synchronizing with an external process.

**Reconstructed caption:** Acquisition-sequence repeat count.



**In context:** The numeric field determines how many complete passes through the enabled channels are executed.

---

<!-- source-pdf-page: 83 -->
## Source PDF page 83

- define if the acquisition must be stopped at the end of the acquisition of the last channel from the last sequence:

- define if the all the measured profiles must be displayed in the same graph. This is possible only if all the channels measure the same type of data:

If the external trigger mode is enabled, it is possible to wait for a trigger condition at the start of each sequence. In such a case, the button named "Trigger each sequence" must be checked. If not checked, the acquisition will start when the external trigger condition is found and ends when the last channel from the last sequence is acquired. The record control panel will allow to display the acquired profiles.

If the external trigger mode is not selected and "Roll over the channels" is checked, at the end of the acquisition of the last channel from the last sequence, the acquisition will be restarted, erasing the previous acquired profile.

- Finally enable the multiplexer

When the multiplexer is enabled, the menus can not be accessed and the parameters can't be changed. The multiplexer is disabled after a click on "Use only one channel".

**Note:** In multiplexing mode, no pre-recorded profiles are available and the value of that parameter is ignored; If the trigger mode is enabled, UDOP will wait until the trigger condition is detected. No pre-trigger profiles are available. The Pre-Trigger profiles parameter is set to 0.

#### Figures and in-context visual analysis

**Reconstructed caption:** Multiplexer and external-trigger options.



**In context:** These options activate channel cycling, optionally synchronize it externally, and decide whether the sequence wraps back after the last channel.

**Reconstructed caption:** Overlay all channels option.



**In context:** When compatible scales permit, channel traces can be overlaid to compare spatial or component measurements directly.

**Reconstructed caption:** Enable-multiplexer command.



**In context:** The channel menu's master checkbox switches the software from single-channel acquisition to the configured sequence.

---

<!-- source-pdf-page: 84 -->
## Source PDF page 84

### 11.3 Switching time

The switching time between channels is in the order of 0.5 ms. During that time some ringings inside the multiplexer will affect the measurement. This implies that the first measured profile after a switch may be affected by this phenomena and can be therefore more noisy.

The life expectancy of the relays depends on the switching rate. We recommend to use a minimum acquisition time of 100 ms pro channel.
