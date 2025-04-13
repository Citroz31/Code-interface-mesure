import pyvisa as visa
import pandas as pd
import os
import numpy as np
import matplotlib.pyplot as plt

rm=visa.ResourceManager()
#print(rm.list_resources())
vna=rm.open_resource('TCPIP0::WFR02L61307_1::hislip_PXI10_CHASSIS1_SLOT1_INDEX0::INSTR')
vna.timeout=5000
# vna.write('*IDN?')
# print(vna.read())
print(vna.query('*IDN?'))
vna.write('*RST')
vna.write('*CLS')
#vna.write('SENS:PATH:CONF 2PORT')

vna.write('CALC:PAR:DEL:ALL')

for i in range(1, 5):
    vna.write(f"DISP:WIND{i}:STAT ON")
# vna.write('DISP:WIND:SPL?')
# print(vna.read())

f_start, f_stop, nb_point=300E3, 20E9, 1001
l_freq=[int(x)/1e9 if x==int(x) else x/1e9 for x in np.linspace(f_start, f_stop, nb_point)]

vna.write('CALC1:PAR:DEF "CH1_S11", S11')
vna.write('CALC1:PAR:DEF "CH1_S21", S21')
vna.write('CALC1:PAR:DEF "CH1_S12", S12')
vna.write('CALC1:PAR:DEF "CH1_S22", S22')

vna.write('DISP:WIND1:TRAC1:FEED "CH1_S11"')
vna.write('DISP:WIND2:TRAC1:FEED "CH1_S21"')
vna.write('DISP:WIND3:TRAC1:FEED "CH1_S12"')
vna.write('DISP:WIND4:TRAC1:FEED "CH1_S22"')

vna.write(f'SENS:FREQ:STAR {f_start}')
vna.write(f'SENS:FREQ:STOP {f_stop}')
vna.write(f'SENS:SWE:POIN {nb_point}')

vna.write('SOUR:POW -10')
vna.write('INIT:CONT OFF')
vna.write('INIT:IMM')
vna.query('*OPC?')

vna.write(f'CALC1:PAR:SEL "CH1_S11"')
vna.write('FORM:DATA REAL,64')
vna.write('FORM:BORD SWAP')

raw=vna.query_binary_values('CALC:DATA? SDATA', datatype='d', is_big_endian=False)
complex_data=np.array(raw[0::2])+1j*np.array(raw[1::2])
s_db=20*np.log10(np.abs(complex_data))
s_phi=np.angle(complex_data, deg=True)
print(s_phi)
plt.figure(figsize=(6,4.2))
plt.plot(l_freq, s_db, linewidth=2)
plt.xlabel('Frequency (GHz)', fontsize=16, fontfamily='Arial')
plt.ylabel('S (dB)', fontsize=16, fontfamily='Arial')
plt.ylim(-50,50)
plt.grid()
plt.show()
vna.close()
rm.close()
