---
title: Chapter 10: Storing and reading measures
manual: DOP3000 Users Manual v6.6.1
pages: 61-75
chapter: 10
---

# 10. Storing and reading measures

This chapter explains in detail how the DOP3000 reads and records measured data
profiles and how it transfers these data to files.
10.1  How data profiles are recorded
When running, the DOP3000 measures continuously data profiles. By means of a panel,
the user can stop the measuring procedure, clear the internal memory or start of a new
measurement. Moreover, with the additional software package “Advanced recording
features”, it is possible to select the profiles that will be recorded to a data file. “The
advanced Trigger option offers the capability to control the recording procedure by an
external trigger signal.
The internal memory is designed in such a way that when a data profile has to be
transferred in the internal memory, the velocimeter checks for the first available free
position and fill this position with the measured values. If no more free positions are
available, the velocimeter replaces the oldest measured data profile by the new one, like
in a FIFO memory (first in, first out). The amount of profiles that the internal memory can
contain is fixed and is equal to 32’000 profiles if the “Advanced recording features”
software package is installed or 1’000 without it. The state of the internal memory is
always indicated in the status bar. When the memory is full a label entitled “Memory: full”
is displayed. In order to insure that all the data profiles are measured and recorded with
the same set of parameters, the DOP3000 erases the internal memory each time a
parameter is changed.
As data are transferred to the PC via the USB port, the exchange of information between
the DOP3000 and the PC must follow the USB rules. This means that the PC checks every
millisecond if a transaction is pending. Unfortunately, is may appears that the acquisition
rate can not be followed by the PC. In such a case, which is seldom, the time between
profiles is no more constant. The time between profiles is then displayed in red to inform
the user of that situation. Reducing the number of gates and/or increasing the number of
emissions pro profile helps to overcome that situation.
Each time a data profile is recorded, additional information linked to the profile is also
recorded. The additional data are:
-
the time stamp in milliseconds * 10
-
the number of the block
-
1 mark byte
-
the number of the multiplexer channel;
-
the data type

10 - 2
Storing and reading measures
Signal Processing S.A. - DOP3000/3010 user’s manual
-
the size of the recorded profile
The DOP3000 puts in its internal memory all the computed and displayed data. This
means that if the user has selected the display of both the velocity profile and the Echo
profile, both profiles will be recorded and will be available in a file if desired. The amount
of bytes used to record a profile will vary, depending on the number of gates used in a
profile and the type of data displayed. For instance, if the instrument displays the velocity
and the echo, using 435 gates, each recorded profile will use:
435 + 435 +22 = 892 bytes.
The added 22 bytes are the additional information bytes (see chapter 9.7)
10.2  Controlling the acquisition
The acquisition of data is controlled by buttons located in the record panel as displayed
below.
This panel can be placed any where on the screen. When the cursor of the mouse
changes to the following figure
(which arises when it is placed over the panel),
maintaining the left button down and moving the mouse moves the panel.
The “Record” button allows to record the future. After clicking, the internal memory is
cleared and the record panel displays only a single “Stop” button. This button allows to
end the acquisition process and store the data.
The “Store” button stores all data contained in the internal memory and therefore record
the passed.
The “Clear and restart” button erases all the memory content.
10.3  Advanced recording features
The additional software package “Advanced recording features” improves the way data
are recorded. With the addition of this package the internal memory can be divided in
many blocks. Up to 65536 blocks can be defined. The maximum size of each block is
defined in the “Preferences” panel (Menu Preferences -> Option) in the button labeled

10 - 3
Storing and reading measures
Signal Processing S.A. - DOP3000/3010 user’s manual
“Do not keep in memory more profiles than”, with a limit of 32’000 profiles, which
corresponds to the maximum available memory space.
This allows to record on a single data file many events or acquisitions. Moreover, before
storing each block, the user can visualize and select a portion of the measured profiles.
Each block is formed by contiguous data profile (in time).
After a click on the “Stop” button or “Pause”, the following panel appears.
By moving the two cursors on the sliding bar the user can display the acquired data and
keep in the recorded data file only the profiles of interest. All the profiles outside the two
cursors will not be included in the record.
If the button “New acquisition” is clicked, the DOP3000 starts a new measurement, and
adds to the internal memory a new block of data.
If the button “Do store” is clicked all the selected profiles from all blocks contained in the
internal memory will be saved to a data file.
Moreover, the user can keep in memory a defined number of profiles just before the user
click on the “Record” button. This number of profiles is defined in the “Preferences”
panel (“Preferences” -> “Options”), in the button named “Number of pre-recorded
profiles”
10.3.1 The Pause button
The “Pause” button stops the acquisition and allows to display the content of the current
recorded block by moving the cursors located on the sliding bar of the panel displayed
below:
This enables to keep in the recorded data file only the profiles of interest, displayed in
green. All the profiles located outside of the two cursors will not be included in the data
file.

10 - 4
Storing and reading measures
Signal Processing S.A. - DOP3000/3010 user’s manual
If the button “Resume” is clicked, the DOP300 starts a new measurement, and adds a
new block of data.
If the button “Do store” is clicked all the blocks are store to a data file.
If the button “Remove current block” is clicked the current block is erased, and the
previous block is accessed.
10.3.2 Skipping profiles
It may be usefull some time to increase the acquisition time. This can be performed by
not recording all the measured profiles and skipping some of them. UDOP includes this
feature. In the “Preferences” panel (“Preferences” -> “Options”), the button named
“Number of skipped profiles” defines the number of profiles that will not be recorded
(place in memory) afer the acquisition of a profile. Nevertheless, these skipped profiles
are mesured and displayed. If this value is set to a non zero value, the status window
indicates that some profiles are skipped by displaying beside the profile counter the
following icon:
The counter does not take into acount the skipped profile.
10.4  External trigger mode
In trigger mode, the acquisition of data profiles is controlled by the state of the external
BNC connector located on the back of the instrument. Trigger is NOT sensitive to an
edge. The external Trigger mode is only available if this optional software package is
installed.
To enable the external Trigger mode:
-
Open the panel “Parameters” from the menu
-
Click “Trigger parameters”
-
Mark “Enable external Trigger”
When the Trigger mode is enabled, the DOP3000 waits until the trigger condition
appears on the BNC. The Trigger condition can be a logic low (voltage below 0.4 Volt)
or a logic high (voltage above 3.6 Volt).

10 - 5
Storing and reading measures
Signal Processing S.A. - DOP3000/3010 user’s manual
CAUTION:
Never apply a voltage lower than 0 volt or higher than 5 Volt to the external trigger
input.
Once the Trigger condition is detected, the DOP3000 acquires the number of profiles as
defined in the field named “and record”. If the button named “Wait for Trigger between
each profile” is checked, the acquisition of the next profile will wait until theTrigger
condition is detected at the BNC. Therefore each profile must satisfy the Trigger
condition.
After the last profile has been acquired, the DOP3000 stops the acquisition. The user can
then store the measured data or repeat a new acquisition.
If the additional software package “Advanced recording features” is installed, the
DOP3000 checks if it must acquire an other set of profiles, which is the case when the
value entered in the button named “Repeat the sequence” is greater than 1.
Note:
The time stamp attached to the first profile acquired just after the Trigger event
is always 0 and should be considered as the time origin.

10.4.1 Field labeled “Keep all profiles”
If the field labeled “Keep all profiles” is unchecked:
When more than one sequence has been entered in the field named “Repeat the sequence” UDOP
will open the record panel to allow the user the visualize and select the profiles to keep.
If the field labeled “Keep all profiles” is checked:
When more than one sequence has been entered in the field named “Repeat the sequence” UDOP
will directly jump to the acquisition of a new sequence, waiting for a new trigger condition, and will
therefore keep all the acquired profiles. Nevertheless the “Keep all profiles” field is checked, the
user will be able to select the profiles to be kept after the end of the last acquisition sequence.
Note:
The “Keep all profiles” field is only available if the “Advanced recording features”
software is installed.
10.4.2 Pre Trigger
If the value entered in the “Pre Trigger” field is 0, the DOP3000 does not measure any
profiles before the trigger event and wait until the trigger condition appears. The delay
between the trigger event and the first emission of the profile that corresponds to the first

10 - 6
Storing and reading measures
Signal Processing S.A. - DOP3000/3010 user’s manual
recorded profile is very short (< 1 s). If the value is not zero, the DOP3000 continuously
measures profiles and keep in its memory the amount of profiles defined in the “Pre
Trigger” field. The delay between the Trigger event and the first emission of the first
profile may vary.
If the “Pre Trigger” field is set to 0, the DOP3000 can wait a user’s defined time if the
value entered in the field named “After Trigger wait” is not 0.
10.5  Storing data to a file
When the profiles to be recorded has been defined, the software opens a panel in which
the user can:
-
select the directory in which the data file will be placed
-
enter the file name
-
add a comment
-
choose the type of generated data file
The “Browse” button allows to select the working directory in which the data will be
placed. The current working directory is displayed in the edit area. This working directory
is by default selected from the “Preferences” panel. Any changes in working directory
will be transferred to the “Preferences” panel.
Do not enter any file extension in the file name area. UDOP will always add the following
extension:
-
“.bdd” for all binary data file
-
“.add” for all ASCII data file
-
“_stat.add” for all statistical ASCII data file
In the comment area, the user can enter any text. The comment will be included in all
type of data file.

10 - 7
Storing and reading measures
Signal Processing S.A. - DOP3000/3010 user’s manual
UDOP always generate a binary data file. The binary format is the only format that
contains all the information related to the measurement. The binary file contains a copy
of all the parameters and all the measured data values are recorded on it. The binary file
format is also the only format that can be read by the UDOP software. All data recorded
in the binary file are raw data; this means that the recorded data do not take into account
any real time computation, such as the applied filters, the velocity offset, the Doppler
angle. This allows the user to post-process the data afterwards.
10.6  The ASCII file format
The ASCII file format is mainly used to transfer data profiles to other software. This format
does not contain the parameters and can not be read afterwards by the UDOP software.
All applied computation parameters, except filters, are used and output data are
calibrated (velocities in mm/s). This means that the output values take into account all
the parameters, such as the sound speed value, the velocity offset, etc....
The resulting output file is a table of values where each line corresponds to a data profile
and each column to a particular depth or gate. At the end of each profile 3 columns are
added. These 3 columns contain the time stamp in milliseconds followed by the number
of the block or sequence and the number of the multiplexer channel.
The first data line of the table gives the depths of the gates. These depths are equivalent
to the distance from the surface of the transducer to the beginning of the sampling
volume.
The structure of the ASCII data file is illustrated in the following figure

10 - 8
Storing and reading measures
Signal Processing S.A. - DOP3000/3010 user’s manual
Each line of data may contain more than one profile. This is the case for instance when
the velocity and the echo profile are displayed during the acquisition. The number of
curves or profiles depends on the the data type. Each cuve is recorded one after the
other in the line. More information on the number of curves in function of the data data
type may be found in the chapter related to the binary format.
Statistical computation in ASCII file format
An additional statistical output data file is also available in an ASCII format. This file gives
the mean, the standard deviation, the minimum and maximum values of all the profiles.
In this file, the time informations (time stamp) is replaced by statistical values of the time
between profiles. The first line of the table gives the mean value, the second the standard
deviation, the third the maximum values and the fourth the minimum values. The table
below gives an example of an ASCII output file with statistical values:
data values
Time stamp in ms
ASCUDOPV2.00.1
Memo_Comments
Gate depth [mm]
1.775
2.525
3.275
4.025
4.775
5.525
6.275
7.025
7.775
8.525
mm/s
mm/s
mm/s
mm/s
mm/s
mm/s
mm/s
mm/s
mm/s
mm/s
TBD [ms] No block Channel
0
0
0
0
0
0
0
0
0
0
0
1
1
0
0
0
0
0
0
0
0
0
0
28.4
1
1
0
0
0
0
0
0
0
0
0
0
56.8
1
1
0
0
0
0
0
0
0
0
0
0
85.2
1
1
0
0
0
0
0
0
0
0
0
0
113.6
1
1
0
0
0
0
0
0
0
0
0
0
142
1
1
0
0
0
0
0
0
0
0
0
0
170.4
1
1
0
0
0
0
0
0
0
0
0
0
198.9
1
1
0
0
0
0
0
0
0
0
0
0
227.3
1
1
0
0
0
0
0
0
0
0
0
0
255.7
1
1
Gives the number of the acquisition block or sequence
Probe channel
data values
Time between profiles in ms
Gives the number of the acquisition block or sequence
Probe channel
ASCUDOPV2.00.1
Memo_Comments
Gate depth [mm]
1.775
2.525
3.275
4.025
4.775
5.525
6.275
7.025
7.775
8.525
mm/s
mm/s
mm/s
mm/s
mm/s
mm/s
mm/s
mm/s
mm/s
mm/s
TBD [ms] No block Channel
Mean Values based on :43 values
113.06
115.93
115.99
114.09
115.71
115.82
115.44
115.61
115.77
116.47
33.29
1
1
Standart deviation
6.11
6.57
6.11
7.04
6.71
6.75
6.47
7.31
6.5
6.29
1.38
1
1
Maximum
125.97
125.97
125.97
125.97
125.97
125.97
125.97
125.97
125.97
125.97
40.8
1
1
Minimum
104.97
104.97
104.97
104.97
104.97
104.97
104.97
104.97
104.97
104.97
32.7
1
1

10 - 9
Storing and reading measures
Signal Processing S.A. - DOP3000/3010 user’s manual
10.7  Structure of the binary file format
The binary file contains eight blocks which are described below in details. The offset
value indicates the offset in bytes from the beginning of the file.
An identification block
offset: 0 to 15
These 16 bytes identify a DOP3000 binary file. Bytes 0 to 7 always contain the following ASCII
characters: BINUDOPV. The software version number in ASCII follows these bytes in the following
format: x.yy.z (for instance 2.00.1). The last 2 bytes of the identification block are always: 0DH, 0AH
A block that contains the comment associated to the measurement
offset:16 (10H) to 527
These 512 bytes contain ASCII characters typed by the user in order to identify the measurement.
This block always ends with the 2 following bytes, 0DH 0AH, so 510 bytes are available for
comments.
A block that contains information on the hardware of the instrument
offset:528 (210H) to 547
These 20 bytes contain information related to the hardware of the instrument and the installed
options.
A block that contains the values of all the parameters
offset: 548 (224H) to 10787
This block contains all the parameters that define the operating conditions of the DOP3000 for all
the channels. 256 parameters are available for each channel. The parameters are stored in a signed
integer format using 32 bits. The table below gives the position and the signification of these
parameters. The value of the position mentioned in the table is relative to the beginning of the table
for a channel. The parameters table for channel 1 is in first position and is followed by channel 2, 3
and so on.
A block that contains the TGC values
offset:10788 (2A24H) to 31267
This block contains the values that define the amplification level for all the channels. Each
amplification value has a byte format. The maximum amplification is given for a value of 255. Each
channel contains 2048 values

10 - 10
Storing and reading measures
Signal Processing S.A. - DOP3000/3010 user’s manual
0
Emitting frequency in kHz
1
assisted Mode: 1 if true
2
User Depth in mm
3
User Velocity in mm/s
4
Quality factor (between 0 and 1000)
5
PRF in s
6
Emission enable if 1
7
Emitting power (0=Low, 1=medium, 2=High)
8
Burst length
9
Indice first gate
10
Resolution (n+1)*0.166ns
11
if 1 auto resolution mode
12
if 1 auto selection of number of gates
13
Number of gates
14
Number of emissions/profile
15
Velocity scale factor (between 0 and 3141)
16
Wall filter coefficient * 1000
17
Number of emissions for stabilization
18
Sensitivity parameter
19
Sound speed in m/s
20
Doppler angle in degrees
21
Module scale (between 256 and 2048)
22
Velocity offset
23
Tgc Mode (0:uniform, 1:slope, 2:auto,
3 custom)
24
Tgc value at the beginning (between 0 and 256)
25
Tgc value at the end (between 0 and 256)
26
TGC gate size (0:0.666 ns 1: 1.333 ns)
27
Bandwidth definition (from 50 kHz (0) to 300
kHz(5), step 50 kHz
28
Overall gain 0: 0db 1:6dB, 2:14 dB, 3:20dB
29
0:acquisition rate 6 MHz, 1: 12 or 40 MHz
30
internal use
31
Type of measurements
0 : Data_Type_Velocity
1 : Data_Type_Echo
2 : Data_Type_Energy
3 : Data_Type_Gate_FFT
4 : Data_Type_Phase_deg_10
5 : Data_Type_Vitson
6 : Data_Type_Frequency
7 : Data_Type_Frequency_TR1
8 : Data_Type_Frequency_TR2
9 : Data_Type_Frequency_TR3
10 :Data_Type_Echo_TR1
11 : Data_Type_Echo_TR2
12 : Data_Type_Echo_TR3
13 : Data_Type_Energy_TR1
14 : Data_Type_Energy_TR2
15 : Data_Type_Energy_TR3
16 : Data_Type_Velocity_mm_s_10;
17 : Data_Type_Velocity_mm_s
18 : Data_Type_Flow_ml_min
19 : Data_Type_Diameter_10
20 : Data_Type_Aliasing_Refer
21 : Data_Type_Aliasing_Refer_TR1
22 : Data_Type_Aliasing_Refer_TR2
23 : Data_Type_Aliasing_Refer_TR3
24 : Data_Type_Frequency_Hz_10
25 : Data_Type_Depth_mm_10
28 : Data_Type_TGC
29 : Data_Type_IQ
30 : Data_Type_Angle_Deg_10
32
Display: 0 horizontal 1: vertical
33
Max number of profiles in a block
34
Trigger mode
bit 1: if set external trigger mode
bit 2: if set trigger on a low logic level
35
Number of profiles keep before trigger
36
Filter 0:none 1:Moving average, 2 median
37
Nb profiles used in moving average
38
if 1 zero rejected in moving average
39
Nb profiles kept before pressing record
DOP3000 parameters table
40
bit 0: if set record binary data file
bit 1: if set record ASCII data file
bit 2: if set record Statistical ASCII data file
41
internal use
42
internal use
43
if 1, emit and receive on the BNC probe In/Out
44
internal use
45
internal use
46
hardware Internal delay in ns
47
Trigger delay in ms
48
Trigger Number of recorded profiles in Block
49
Trigger: Number of blocks
50
Trigger: Auto record starting counter value
51
Nb profiles in block in multiplexer mode
52
bit 1: if set multiplexer enables
bit 2: if set UDV MD mode
bit 3: if set UDV 3D, else UDV 2D
bit 4 to 13: channel selected if bit = 1
bit 15-31 : first channel
53
Nb blocks in multiplexer mode
54
Nb of profiles used by median filter
55
if 1, echo mode
56
internal use
57
internal use
58
number of points for gate FFT
59
if 1, Gate FFT use Haming window
60
internal use
61Time scale for V(t) in ms
62
sound speed measuring distance in m*10
63
UDV MD, emit probe reference
64
UDV MD, receive probe reference
65
UDV MD, distance between probes, mm*10
66
UDV MD, Doppler angle in deg
67
UDV MD, Vx max in mm/s *10
68
UDV MD, Vy max in mm/s *10
69
UDV MD, Vz max in mm/s *10
70
UDV MD, TR1 frequency offset -127 -> 128
71
UDV MD, TR2 frequency offset -127 -> 128
72
UDV MD, TR3 frequency offset -127 -> 128
73
UDV MD, Scale angle for TR1, in rad*1000
74
UDV MD, Scale angle for TR2, in rad*1000
75
UDV MD, Scale angle for TR3, in rad*1000
76
UDV MD, Module scale for TR1
77
UDV MD, Module scale for TR2
78
UDV MD, Module scale for TR3
79
UDV MD, depth from in mm
80
UDV MD, depth to in mm
81
UDV MD, Resolution mm*10
82
UDV MD, quality factor
83
Current channel
84
skip profile
85
Simul Velocity scale factor
86
liquid attenuation in dB/cm * 1000
87
Simul selected gate in IQ display
88
none
89
UDV MD Nb skipped vectors
90
Raw data acquisition, Nb PRF
91
Raw data acquisition, Nb gates
92
Raw data acquisition, First gate
93
Overall gain in dB
94
Cursor 1 on gate
95
Cursor 2 on gate
96
Cursor 3 on gate
97
Cursor 4 on gate
98
UDV 2D/3D simulation, from
99
UDV 2D/3D simulation, To
100
UDV 2D/3D simulation, X source pos
101
UDV 2D/3D simulation, Y source pos
102
UDV 2D/3D simulation, Z source pos
103
Max attenuation in simulation in dB
104
UDV 2D/3D simulation, Part density
105
UDV 2D/3D simulation, Velocity field type
106
UDV 2D/3D simulation, Rotation speed
107
UDV 2D/3D simulation, Shift TR1
108
UDV 2D/3D simulation, Shift TR2
109
UDV 2D/3D simulation, Shift TR3
110
UDV 2D/3D simulation, Adapt PRF
111
Flow rate Unit
0 : ml/min
1 : ml/s
2 : dl/s
112
Flow rate scale
113
Auto Correct Aliasing Control word 1
114
Auto Correct Aliasing Control word 2
115
sound speed in wall
116
Length of wall
117
sound speed in couplant
118
length of couplant
119
US emitting frequency divider
120
demodulation frequency divider
121
DOP4000 control register 1
122
DOP4000 control register 2
123
Nb classes for histogram

10 - 11
Storing and reading measures
Signal Processing S.A. - DOP3000/3010 user’s manual
A block that contains the values of the data profiles
offset 31268 (7A24H) to the end of the file
This block contains all the measured data profiles and starts with one or more pseudo profiles that
gives the measurements depths. The appellation of pseudo profile means that these first profiles are
not measured data but are recorded the same way as normal data profile. The data type information
byte identify this type of profile. These pseudo profiles give the values of the abscissa of the graphs.
If only one channel is used, only one pseudo profile is added to the data file. This first profile
contains as many abscissa values as the number of curves or graphs. If many channels have been
measured, there will be one pseudo profile for each channel, the first one corresponding to the
starting channel.
Each profile is formed by the following bytes. Starting from the beginning of the profile:
A 1 word (2 bytes) that gives the total number of bytes used by all the curves inside a profile.
B 1 word (2 bytes) that gives the number N1 of bytes of the following curve or graph. If N1
= 0 no data follow and the next bytes are those described from point E.
C 1 byte that identify the type of data:
See parameter 31 in the parameter table
D N1 bytes of data
Each data value are in a byte format except for
Data type:
4, 16, 17, 19, 24, 25, 30  data in format 16 bits
Data type:
18 data in format 32 bits
if data type is 29 (raw data) the format is 16 bits signed integer, and the raw data are
recorded as follow:
I1,Q1,I2,Q2,I3......In,Qn (n = N1/2)
After these data bytes the next one has the meaning defined at point B.
E
a long word (4 bytes) that gives the time stamp in milliseconds * 10
F
a (2 bytes) word that gives the block number
G a mark byte
H 1 byte that gives the state of the BNC Trigger input
I
1 reserved bytes (no meaning)
J
a byte which gives the number of multiplexer channel
K a word (2 bytes) that gives the total number of bytes used by the profile (same value as in
point A).

10 - 12
Storing and reading measures
Signal Processing S.A. - DOP3000/3010 user’s manual
10.7.1 The time stamp
At each profile a time stamp is attached, which gives the time at which the profile is
measured (time of the transfer from the ultrasonic processor to the internal memory). The
accuracy of this time is not affected by any Windows operations and its unit is in
milliseconds * 10.
Depending on the acquisition mode (passed or future), UDOP software fixes the time
origin to:
-
the first profile in the block when the user select to acquire the passed
-
the time when the user click on the “Record” button when the user select to
acquire the future.
-
the Trigger event if the external Trigger mode is enabled.
10.7.2 Structure of a binary file if the aliasing is corrected
If the aliasing is corrected (Auto correction ON), the binary profiles contain one (or more
in UDV 2D/3D) additional curve. This curve contains the corrected velocity values,
calibrated in mm/s or mm/s*10 depending the value of data type information byte.
If the corrected method is based on the two PRF method, the added curve contains the
corrected curve if this curve was displayed during the measurement or, if not visible, the
values of the reference profile.
Table 2:
compute
Auto correction of the aliasing
Off
Two PRF
Jump
Velocity (o)
Velocity + V(t) (33)
Velocity + color
code (50)
- coded velocity (byte)
- coded velocity (byte)
- reference profile (byte)
- calibrated velocity (word)
- coded velocity (byte)
- calibrated velocity (word)
Echo or Energy
(1,2)
- coded echo (byte)
- coded echo Prf 1(byte)
- coded echo Prf 2(byte)
- coded echo (byte)
Velocity + Echo/
Eneg
(30,31)
- coded velocity (byte)
- coded amplitude (byte)
- coded velocity (byte)
- reference profile (byte)
- coded echo Prf 1(byte)
- coded echo Prf 2(byte)
- calibrated velocity (word)
- coded velocity (byte)
- coded amplitude (byte)
- calibrated velocity (word)

10 - 13
Storing and reading measures
Signal Processing S.A. - DOP3000/3010 user’s manual
10.7.3 Structure of a binary file in UDV 2D/3D
In UDV 2D/3D mode, the first curves in the profile always contain the coded Doppler
frequency issue from each receiver (1 curve for each receiver, starting by receiver 1),
except in echo mode where they contain the echo amplitude. These curves are followed
by calibrated values depending on the selection of the computed mode.
If the computed mode is “Doppler frequency”, calibrated curves are only added if the
auto correction of the aliasing was enabled. These added curves contain the Doppler
frequency issue from each receivers in Hz*10
If the computed mode is “Velocity Vx, Vy”, the following added curves contain the
velocity components Vx, Vy and Vz in 3D. The unit depends on the value of data type
information byte (mm/s or mm/s*10
If the computed mode is “Velocity Module, phase”, the following added curves contain
the modulus of the velocity vector, in mm/s or mm/s*10 depending on the value of data
type information byte, followed by the azimuthal angle in degree*10 and by the elevation
angle, in degrees *10, in case of UDV 3D.
velocity + gate
spectrum
(32)
- coded velocity (byte)
- coded FFT amplitude
(byte)
Not available
Not available
Velocity + flow rate
(36)
- coded velocity (byte)
- flow rate value (1 long int)
- coded velocity (byte)
- reference profile (byte)
- calibrated velocity (word)
- flow rate value (1 long int)
- coded velocity (byte)
- calibrated velocity (word)
- flow rate value (1 long int)
Table 3:
compute
Auto correction of the aliasing
Off
Two PRF
Jump
Frequency(40)
- coded Freq Rec1(byte)
- coded Freq Rec2(byte)
- coded Freq Rec1(byte)
- refer profile Rec1 (byte)
- coded Freq Rec2(byte)
- refer profile Rec2 (byte)
- calib Freq Rec1(word)
- calib Freq Rec2(word)
- coded Freq Rec1(byte)
- coded Freq Rec2(byte)
- calib Freq Rec1(word)
- calib Freq Rec2(word)
Echo (41)
- coded echo Rec1(byte)
- coded echo Rec2(byte)
- coded echo Prf 1, Rec1
- coded echo Prf 2, Rec1
- coded echo Prf 1, Rec2
- coded echo Prf 2, Rec2
- coded echo Rec1(byte)
- coded echo Rec2(byte)
Velocity
components
(42)
- coded Freq Rec1(byte)
- coded Freq Rec2(byte)
- calibrated Vy (word)
- calibrated Vz (word)
- coded Freq Rec1(byte)
- refer profile Rec1 (byte)
- coded Freq Rec2(byte)
- refer profile Rec2 (byte)
- calibrated Vy (word)
- calibrated Vz (word)
- coded Freq Rec1(byte)
- coded Freq Rec2(byte)
- calibrated Vy (word)
- calibrated Vz (word)
Table 2:

10 - 14
Storing and reading measures
Signal Processing S.A. - DOP3000/3010 user’s manual
10.8  Conversion of a coded Doppler frequency
The recorded Doppler frequency values are coded and are in a byte format. In order to
convert these coded values in a Doppler frequency Fdop in Hz, you should applied the
following relation
where:
Val
is the coded value extracted from the file. It has a value between -128 et +127
Velocity module
and azimut
(43)
- coded Freq Rec1(byte)
- coded Freq Rec2(byte)
- calibrated module(word)
- calibrated azimut (word)
- coded Freq Rec1(byte)
- refer profile Rec1 (byte)
- coded Freq Rec2(byte)
- refer profile Rec2 (byte)
- calibrated module(word)
- calibrated azimut (word)
- coded Freq Rec1(byte)
- coded Freq Rec2(byte)
- calibrated module(word)
- calibrated azimut (word)
Table 4:
compute
Auto correction of the aliasing
Off
Two PRF
Jump
Frequency(60)
- coded Freq Rec1 (byte)
- coded Freq Rec2 (byte)
- coded Freq Rec3 (byte)
- coded Freq Rec1(byte)
- refer profile Rec1 (byte)
- coded Freq Rec2 (byte)
- refer profile Rec2 (byte)
- coded Freq Rec3 (byte)
- refer profile Rec3 (byte)
- calib Freq Rec1 (word)
- calib Freq Rec2 (word)
- calib Freq Rec3 (word)
- coded Freq Rec1 (byte)
- coded Freq Rec2 (byte)
- coded Freq Rec3 (byte)
- calib Freq Rec1 (word)
- calib Freq Rec2 (word)
- calib Freq Rec3 (word)
Echo (61)
- coded echo Rec1 (byte)
- coded echo Rec2 (byte)
- coded echo Rec3 (byte)
- coded echo Prf 1, Rec1
- coded echo Prf 2, Rec1
- coded echo Prf 1, Rec2
- coded echo Prf 2, Rec2
- coded echo Prf 1, Rec3
- coded echo Prf 2, Rec3
- coded echo Rec1 (byte)
- coded echo Rec2 (byte)
- coded echo Rec3 (byte)
Velocity
components
(62)
- coded Freq Rec1 (byte)
- coded Freq Rec2 (byte)
- coded Freq Rec3 (byte)
- calibrated Vx (word)
- calibrated Vy (word)
- calibrated Vz (word)
- coded Freq Rec1 (byte)
- refer profile Rec1 (byte)
- coded Freq Rec2 (byte)
- refer profile Rec2 (byte)
- coded Freq Rec3 (byte)
- refer profile Rec3 (byte)
- calibrated Vx (word)
- calibrated Vy (word)
- calibrated Vz (word)
- coded Freq Rec1 (byte)
- coded Freq Rec2 (byte)
- coded Freq Rec3 (byte)
- calibrated Vx (word)
- calibrated Vy (word)
- calibrated Vz (word)
Velocity module
and azimut
(63)
- coded Freq Rec1 (byte)
- coded Freq Rec2 (byte)
- coded Freq Rec3 (byte)
- calibrated module(word)
- calibrated azimut (word)
- calibrated elevation (word)
- coded Freq Rec1 (byte)
- refer profile Rec1 (byte)
- coded Freq Rec2 (byte)
- refer profile Rec2 (byte)
- coded Freq Rec3 (byte)
- refer profile Rec3 (byte)
- calibrated module(word)
- calibrated azimut (word)
- calibrated elevation
(word)
- coded Freq Rec1 (byte)
- coded Freq Rec2 (byte)
- coded Freq Rec3 (byte)
- calibrated module(word)
- calibrated azimut (word)
- calibrated elevation
(word)
Table 3:

10 - 15
Storing and reading measures
Signal Processing S.A. - DOP3000/3010 user’s manual
Par[x]
is the binary value (format signed integer 4 bytes) located at offset x from the beginning
of the binary parameters bloc.
The relation above is valid only if the velocity offset value is 0 (equal range for positive
and negative value). If the velocity offset is not 0 the recorded binary values have to be
corrected by the following algorithm before using the above formula.
The Doppler frequency in Hz can be converted in a velocity by the relation below, which
gives the velocity component in the direction of the ultrasonic beam.
where:
FDop
is the Doppler frequency in Hz computed by the preceding relation.
Par[x]
is the binary value (format signed integer 4 bytes) located at offset x from the beginning
of the binary parameters bloc.
10.9  Extraction of the depth of a gate
The depth of a gate is given by its position in a profile. The gate located at the lowest
depth is placed at the beginning of a profile. The following equation can be used to
extract the depth in millimeters of a particular gate
FDop Hz


Val
Par 15



103

Par 5

256



-------------------------------------------------
=
Val = Val + Par(22)
ICOR = 0
IF Val > 127 then ICOR = -256
IF Val < -128) then ICOR = 256
Val = Val + ICOR
Val = Val - Par(22)
V m s



FDop
Par 19



2
COS Par 20




P


ar 0

103

------------------------------------------------------------------------------------
=

10 - 16
Storing and reading measures
Signal Processing S.A. - DOP3000/3010 user’s manual
:
where:
Par[x]
is the binary value (format signed integer 4 bytes) located at offset x from the beginning
of the binary parameters bloc.
i
the gate number, starting from 1.
Note:
The binary data file includes also a pseudo profile that contains the values of the
depths of all the gates.
10.10  Reading a binary DOP3000 file
The DOP3000 can read and replay a measure from a binary DOP3000 file. The binary
file format is the only file format that can be read by the UDOP software. Reading or
replaying a measure allows the user to visualize slowly the measured profiles, to post
process the data profiles and also to re-record the data with new processing conditions.
This last point enables to change the file format, to compute statistical values and to save
and keep only a portion of the measured data profiles.
When replayed, the data profiles can be visualized step by step, in a forward or
backward direction, or continuously with the adjunction of a user’s defined delay
between each profile. In replay mode, the status window displays no more the time
between acquired profiles but the time elapsed from the first profile of the file in
milliseconds. All the menus that are used to define a parameter value that fixes the
acquisition characteristic are disabled and only the value used during the acquisition of
data profiles are shown.
Note:
An easy way to visualize the parameters values used in a binary data file consists
to recall the parameters from the file. (“parameters” -> “Recall parameters” ->
“From file”)
Depth mm


Par 19


Par 9

Par 10


1
+

i
1
–


+
