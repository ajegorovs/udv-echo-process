# 3. Installing the software

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 17-20.

---

<!-- source-pdf-page: 17 -->
## Source PDF page 17

## 3 Installing the software

This chapter explains how to install the software UDOP and the USB driver that controls the DOP3000 series ultrasonic Doppler velocimeter. The driver installation is realized only once on the connected PC.

You should follow the steps below:

- get the software from our web site.
- installing the software driver
- install the UDOP software
- connecting the cables
- switching on the power supply of the velocimeter
- running the UDOP software

### 3.1 Getting the software

The software that controls the DOP3000 series, UDOP, and the associated USB driver is available on our website at the following address:

http://www.signal-processing.com/dop3000_download.html

Download the following zip file "dop3000_update_v_vv_v.zip" where v_vv_v represents the software version and unzip that file to a directory of your choice. This directory will be the directory that will contain UDOP software and must contain the following directories:

- DRIVER - MANUAL - UTILITIES - US_FIELD_DATA and the following files: - udop3000.chm - ftd2xx.dll - Udopvvvv.exe (vvvv represent the software version) - Udop21262_vvvv.bin

---

<!-- source-pdf-page: 18 -->
## Source PDF page 18

### 3.2 Installing the software driver

The driver to install is contained in an ".exe" file located in the directory named "driver". After a click on that file the following display appears:

Accept the extraction:

Then accept the installation:

If the installation is successful, the following displays appears:"

#### Figures and in-context visual analysis

**Reconstructed caption:** FTDI driver package extraction window.



**In context:** The first installation screenshot shows unpacking the USB serial driver before Windows launches its device-installation wizard.

**Reconstructed caption:** Windows hardware-driver wizard.



**In context:** The wizard is the second stage of driver installation and confirms that the operating system is locating the extracted FTDI driver files.

**Reconstructed caption:** FTDI licence agreement.



**In context:** The driver installation cannot continue until the licence terms are accepted; the screenshot locates the required choice in the wizard.

**Reconstructed caption:** Completed FTDI driver installation.



**In context:** The final wizard screen reports both USB serial components as ready, marking the point at which the DOP can be connected and detected.

---

<!-- source-pdf-page: 19 -->
## Source PDF page 19

### 3.3 Connecting the cables

Before connecting the DOP3000 to the power supply line, be sure that the voltage selection switch is set for the correct line voltage. Connect the USB port of the DOP3000 to any available USB 2 compatible port on the PC. The DOP3000 do not request power from the USB port. Then turn on the power switch. Windows will then detect the DOP3000.

### 3.4 What to do in case of troubles during the installation of the driver?

If a wrong answer is given during the installation procedure, the installation may failed. In such a case you have to re-install again the driver.

More information on the driver can be found on the website: http://www.ftdichip.com/Drivers/D2XX.htm

### 3.5 What to do if the application do not start?

The application UDOP uses a configuration file, named:

- UDOP3000_nnn_vvvv_CFG.BIN where nnn is a 3 digits that identifies the instrument and vvvv identifies the software version or - UDOPCFG_vvvv.BIN if in simulation

that contains the working parameters. If the file is corrupted or contains incorrect parameters, UDOP can not be executed. In such a case you must delete the configuration file. If no configuration file is detected at start-up, UDOP will create a new one, containing the default parameters.

### 3.6 Connecting more then one DOP to the same PC?

UDOP can recognize up to 4 different DOP3000 or DOP4000 velocimeters. This means that you can connect to the same PC up to four instruments. For each velocimeter you must launch the UDOP application. UDOP identifies the instrument by its serial number, which is displayed in the title bar of the application. Each instrument keeps in a file its own functioning parameters.

---

<!-- source-pdf-page: 20 -->
## Source PDF page 20

**Note:** The size of the UDOP window can be resized as desired, following the same procedure as for any windows applications. If the acquisition time is very fast, it may appear that the PC can't follow the acquisition rate for all the instruments.
