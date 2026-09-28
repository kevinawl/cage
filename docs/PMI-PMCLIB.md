# Talking to the PMI planar motor from C#

Findings from taking apart `pmclib-117.15.01-py3` (the wheel in `~/Downloads`) and
reading the [Planar Motor software manual](https://docs.planarmotor.com/tech-portal/software-manual).

## PMCLIB.dll is a .NET assembly

The Python package is only a thin **pythonnet** wrapper — `pmc_commands.py` does
`from System import Enum`, which is .NET, not ctypes. The real library is
`PMCLIB.dll` inside the wheel:

- managed .NET assembly, **targeting `netstandard2.0`**, MSIL / AnyCPU
- Fennec targets `net10.0` / `win-x64`, which loads netstandard2.0 without complaint

**So C# references it directly.** No Python subprocess, no P/Invoke, no reverse
engineering the TCP protocol. PMLib lists "Visual Studio .NET" as a supported PC
platform, so this is the sanctioned path.

Get the proper .NET distribution from PMI rather than shipping a DLL scraped out of
a Python wheel — the assembly version inside (117.1.1.0) does not match the package
version (117.15.1) anyway.

## The calls that matter

```csharp
bool        ConnectToSpecificPMC(string ipAddress)   // default PMC is 192.168.10.100
bool        AutoSearchAndConnectToPMC()
PMCRTN      GainMastership() / ReleaseMastership()
bool        IsMaster()
AllXBotInfo GetAllXbotInfo(ALLXBOTSFEEDBACKOPTION feedbackOption)   // POSITION | REFERENCE
XBotStatus  GetXbotStatus(int xbotID, FEEDBACKOPTION feedbackType)
void        LinearMotionSI(...)                      // commanding, for the sweep
```

Entry point class is `PMCCommands`.

`GetAllXbotInfo` is the poll call — every mover's full pose in one round trip:

```csharp
class XBotInfo {
    double    XPos, YPos, ZPos;      // SI, metres
    double    RxPos, RyPos, RzPos;   // rotations — full 6-DOF
    XBOTSTATE XBotState;
    int       XbotID;
    XBOTTYPE  XbotType;
}
```

Log all six from the start. Rotations cost nothing extra — they arrive in the same
struct from the same call — and coupling depends on coil angle, not just distance,
so tilt is what explains otherwise-unreproducible scatter.

## Polling only

There is no push or streaming interface on the Ethernet side. "Auto Refresh" in the
manual is a Fieldbus function block you call once per PLC cycle, not a subscription.
Poll `GetAllXbotInfo` on a timer.

## Connection vs. control

Connecting and controlling are deliberately separate. The manual: mastership
*"ensures only 1 Ethernet program can have control of the system at a time."*
Control, not connection — and `GainMastership()` returns a `PMCRTN` that can fail,
which only makes sense if several clients can be connected at once.

**Not confirmed:** whether a non-master client can still *read* status. Neither the
Gain Mastership nor the Connect page says. Test it (connect a second machine, skip
`GainMastership()`, call `GetAllXbotInfo`) or ask solutions@planarmotor.com.

For a sweep this is moot — the tool driving the bench should hold mastership.

## xBots carry no electronics

The mover is a passive permanent-magnet array. Position is sensed by the stator
tiles and reported by the PMC. There is **no data channel to or from the mover** —
no payload sensor interface, no wireless I/O. Every command category in the manual
was checked; the closest thing is RFID, used only to identify which physical mover
is which.

If something riding on the mover needs to be measured, that telemetry is ours to
build. Better: arrange the bench so everything measuring is stationary and wired,
and let PMI only report where the moving part is.

## Network reachability

The PMC is a device on the Ethernet network at an IP, not something plugged into a
particular computer. Any machine that can route to that subnet can reach it,
including over Wi-Fi — the PMC only sees an incoming TCP connection.

The one thing that would block it: if the PMC's cable runs directly into a single
PC's Ethernet port rather than into a switch. The `192.168.10.x` default hints at
exactly that kind of isolated link. Check with:

```powershell
Test-NetConnection 192.168.10.100 -InformationLevel Detailed
```

Note that the instruments are the real constraint on where Fennec runs — VISA over
USB and MCUs on COM ports only exist on the machine they are plugged into. The PMC
is the most shareable device in the setup.
