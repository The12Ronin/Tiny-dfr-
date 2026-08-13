#!/usr/bin/env python3
"""
patch_layer3.py - adds a third tiny-dfr layer with live system indicators
(CPU usage, temperature, memory) that change color with their value.

Usage:
    python3 patch_layer3.py ~/tiny-dfr
    python3 patch_layer3.py ~/tiny-dfr --revert
"""

import re
import shutil
import sys
import os

# ---------------------------------------------------------------- config.rs

CFG_ESC_HELPER = '''fn esc_button() -> ButtonConfig {
    ButtonConfig {
        icon: None,
        text: Some("esc".into()),
        theme: None,
        action: vec![Key::Esc],
        stretch: None,
        time: None,
        locale: None,
        battery: None,
        sysinfo: None,
        icon_width: None,
        icon_height: None,
    }
}

fn load_config('''

CFG_LAYERS = '''    let mut system_layer_keys = base.system_layer_keys.unwrap_or_default();
    if width >= 2170 && !system_layer_keys.is_empty() {
        system_layer_keys.insert(0, esc_button());
    }
    let media_layer = FunctionLayer::with_config(media_layer_keys);
    let fkey_layer = FunctionLayer::with_config(primary_layer_keys);
    let mut layers = if base.media_layer_default.unwrap() {
        vec![media_layer, fkey_layer]
    } else {
        vec![fkey_layer, media_layer]
    };
    if !system_layer_keys.is_empty() {
        layers.push(FunctionLayer::with_config(system_layer_keys));
    }
'''


def patch_config(text):
    steps = []

    # 1. new field in ConfigProxy
    text, n = re.subn(
        r"(    media_layer_keys: Option<Vec<ButtonConfig>>,\n)\}",
        r"\1    system_layer_keys: Option<Vec<ButtonConfig>>,\n}",
        text, count=1)
    steps.append(("ConfigProxy.system_layer_keys", n))

    # 2. new field in ButtonConfig
    text, n = re.subn(
        r"(    pub battery: Option<String>,\n)",
        r"\1    pub sysinfo: Option<String>,\n",
        text, count=1)
    steps.append(("ButtonConfig.sysinfo", n))

    # 3. merge user config
    text, n = re.subn(
        r"(        base\.primary_layer_keys = user\.primary_layer_keys\.or\(base\.primary_layer_keys\);\n)",
        r"\1        base.system_layer_keys = user.system_layer_keys.or(base.system_layer_keys);\n",
        text, count=1)
    steps.append(("merge system_layer_keys", n))

    # 4. array -> Vec everywhere
    text, n = re.subn(r"\[FunctionLayer; 2\]", "Vec<FunctionLayer>", text)
    steps.append(("[FunctionLayer; 2] -> Vec", n))

    # 5. esc button helper
    text, n = re.subn(r"fn load_config\(", CFG_ESC_HELPER, text, count=1)
    steps.append(("esc_button() helper", n))

    # 6. use the helper inside the insertion loop
    text, n = re.subn(
        r"            layer\.insert\(\s*0,\s*ButtonConfig \{.*?\},\s*\);",
        "            layer.insert(0, esc_button());",
        text, count=1, flags=re.S)
    steps.append(("esc insert uses helper", n))

    # 7. build the layer vector
    text, n = re.subn(
        r"    let media_layer = FunctionLayer::with_config\(media_layer_keys\);\n"
        r"    let fkey_layer = FunctionLayer::with_config\(primary_layer_keys\);\n"
        r"    let layers = if base\.media_layer_default\.unwrap\(\) \{\n"
        r"        \[media_layer, fkey_layer\]\n"
        r"    \} else \{\n"
        r"        \[fkey_layer, media_layer\]\n"
        r"    \};\n",
        lambda _: CFG_LAYERS,
        text, count=1)
    steps.append(("layer vector", n))

    return text, steps


# ----------------------------------------------------------------- main.rs

MAIN_METRICS = '''#[derive(Clone, Copy, PartialEq, Eq)]
enum SysMetric {
    Cpu,
    Temp,
    Mem,
}

static CPU_PREV_TOTAL: AtomicU64 = AtomicU64::new(0);
static CPU_PREV_IDLE: AtomicU64 = AtomicU64::new(0);
static CPU_CACHE: AtomicU64 = AtomicU64::new(0);
static CPU_CACHE_MS: AtomicU64 = AtomicU64::new(0);
static TEMP_CACHE: AtomicU64 = AtomicU64::new(0);
static TEMP_CACHE_MS: AtomicU64 = AtomicU64::new(0);
static MEM_CACHE: AtomicU64 = AtomicU64::new(0);
static MEM_CACHE_MS: AtomicU64 = AtomicU64::new(0);

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn cached(cache: &AtomicU64, stamp: &AtomicU64, f: fn() -> f64) -> f64 {
    let now = now_ms();
    let last = stamp.load(AtomicOrdering::Relaxed);
    if last != 0 && now.saturating_sub(last) < 500 {
        return cache.load(AtomicOrdering::Relaxed) as f64 / 1000.0;
    }
    let v = f();
    cache.store((v * 1000.0) as u64, AtomicOrdering::Relaxed);
    stamp.store(now, AtomicOrdering::Relaxed);
    v
}

fn read_cpu_usage() -> f64 {
    let stat = match fs::read_to_string("/proc/stat") {
        Ok(s) => s,
        Err(_) => return 0.0,
    };
    let line = match stat.lines().next() {
        Some(l) => l,
        None => return 0.0,
    };
    let vals: Vec<u64> = line
        .split_whitespace()
        .skip(1)
        .filter_map(|v| v.parse().ok())
        .collect();
    if vals.len() < 4 {
        return 0.0;
    }
    let idle = vals[3] + vals.get(4).copied().unwrap_or(0);
    let total: u64 = vals.iter().sum();
    let prev_total = CPU_PREV_TOTAL.swap(total, AtomicOrdering::Relaxed);
    let prev_idle = CPU_PREV_IDLE.swap(idle, AtomicOrdering::Relaxed);
    if total <= prev_total {
        return 0.0;
    }
    let dt = (total - prev_total) as f64;
    let di = idle.saturating_sub(prev_idle) as f64;
    (((dt - di) / dt) * 100.0).clamp(0.0, 100.0)
}

fn read_temperature() -> f64 {
    let mut best = 0.0;
    if let Ok(entries) = fs::read_dir("/sys/class/thermal") {
        for entry in entries.flatten() {
            let path = entry.path();
            let is_zone = path
                .file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.starts_with("thermal_zone"))
                .unwrap_or(false);
            if !is_zone {
                continue;
            }
            if let Ok(raw) = fs::read_to_string(path.join("temp")) {
                if let Ok(v) = raw.trim().parse::<f64>() {
                    let c = v / 1000.0;
                    if c > best && c < 150.0 {
                        best = c;
                    }
                }
            }
        }
    }
    best
}

fn read_mem_usage() -> f64 {
    let info = match fs::read_to_string("/proc/meminfo") {
        Ok(s) => s,
        Err(_) => return 0.0,
    };
    let mut total = 0.0;
    let mut avail = 0.0;
    for line in info.lines() {
        let mut parts = line.split_whitespace();
        let key = parts.next().unwrap_or("");
        let val: f64 = parts.next().and_then(|v| v.parse().ok()).unwrap_or(0.0);
        match key {
            "MemTotal:" => total = val,
            "MemAvailable:" => avail = val,
            _ => {}
        }
    }
    if total <= 0.0 {
        return 0.0;
    }
    (((total - avail) / total) * 100.0).clamp(0.0, 100.0)
}

impl SysMetric {
    fn value(self) -> f64 {
        match self {
            SysMetric::Cpu => cached(&CPU_CACHE, &CPU_CACHE_MS, read_cpu_usage),
            SysMetric::Temp => cached(&TEMP_CACHE, &TEMP_CACHE_MS, read_temperature),
            SysMetric::Mem => cached(&MEM_CACHE, &MEM_CACHE_MS, read_mem_usage),
        }
    }
    fn label(self) -> String {
        match self {
            SysMetric::Cpu => format!("CPU {:.0}%", self.value()),
            SysMetric::Temp => format!("{:.0} C", self.value()),
            SysMetric::Mem => format!("MEM {:.0}%", self.value()),
        }
    }
    fn color(self) -> (f64, f64, f64) {
        let v = self.value();
        let ratio = match self {
            SysMetric::Temp => (v / 90.0).clamp(0.0, 1.0),
            _ => (v / 100.0).clamp(0.0, 1.0),
        };
        if ratio < 0.5 {
            (0.20, 0.85, 0.35)
        } else if ratio < 0.75 {
            (1.00, 0.75, 0.10)
        } else {
            (1.00, 0.25, 0.20)
        }
    }
}

enum ButtonImage {'''

MAIN_NEW_SYSINFO = '''    fn new_sysinfo(action: Vec<Key>, kind: &str) -> Button {
        let metric = match kind.to_lowercase().as_str() {
            "cpu" => SysMetric::Cpu,
            "temp" | "temperature" => SysMetric::Temp,
            "mem" | "memory" | "ram" => SysMetric::Mem,
            _ => panic!("invalid Sysinfo value, accepted values: cpu, temp, mem"),
        };
        Button {
            action,
            active: false,
            changed: false,
            image: ButtonImage::SysInfo(metric),
            icon_width: 0.0,
            icon_height: 0.0,
        }
    }
    fn new_text('''

MAIN_RENDER_ARM = '''            ButtonImage::SysInfo(metric) => {
                let text = metric.label();
                let extents = c.text_extents(&text).unwrap();
                c.move_to(
                    button_left_edge + (button_width as f64 / 2.0 - extents.width() / 2.0).round(),
                    y_shift + (height as f64 / 2.0 + extents.height() / 2.0).round(),
                );
                c.show_text(&text).unwrap();
            }
            ButtonImage::Spacer => (),'''

MAIN_SYS_BRANCH = '''        } else if let ButtonImage::SysInfo(metric) = &self.image {
            let (r, g, b) = metric.color();
            let k = if self.active {
                BUTTON_TINT_ACTIVE
            } else {
                BUTTON_TINT_INACTIVE
            };
            c.set_source_rgb(r * k, g * k, b * k);
        } else {
            '''

MAIN_LOOP_BLOCK = '''        if layers[active_layer].displays_sysinfo {
            next_timeout_ms = min(next_timeout_ms, 1000);
            for button in &mut layers[active_layer].buttons {
                if let ButtonImage::SysInfo(_) = button.1.image {
                    button.1.changed = true;
                }
            }
        }
        if layers[active_layer].displays_battery {'''


def patch_main(text):
    steps = []

    # 1. atomics import
    text, n = re.subn(
        r"(use udev::MonitorBuilder;\n)",
        r"\1use std::sync::atomic::{AtomicU64, Ordering as AtomicOrdering};\n",
        text, count=1)
    steps.append(("atomic import", n))

    # 2. metric readers
    text, n = re.subn(r"enum ButtonImage \{", MAIN_METRICS, text, count=1)
    steps.append(("SysMetric + readers", n))

    # 3. enum variant
    text, n = re.subn(
        r"(    Battery\(String, BatteryIconMode, BatteryImages\),\n)",
        r"\1    SysInfo(SysMetric),\n",
        text, count=1)
    steps.append(("ButtonImage::SysInfo", n))

    # 4. constructor
    text, n = re.subn(r"    fn new_text\(", MAIN_NEW_SYSINFO, text, count=1)
    steps.append(("new_sysinfo()", n))

    # 5. with_config branch
    text, n = re.subn(
        r"        \} else \{\n            Button::new_spacer\(\)\n        \}",
        "        } else if let Some(kind) = cfg.sysinfo {\n"
        "            Button::new_sysinfo(cfg.action, &kind)\n"
        "        } else {\n            Button::new_spacer()\n        }",
        text, count=1)
    steps.append(("with_config branch", n))

    # 6. render arm
    text, n = re.subn(
        r"            ButtonImage::Spacer => \(\),",
        lambda _: MAIN_RENDER_ARM,
        text, count=1)
    steps.append(("render arm", n))

    # 7. background color branch
    text, n = re.subn(
        r"\}\s*else\s*\{\s*let \(r, ?g, ?b\) = BUTTON_PALETTE",
        lambda _: MAIN_SYS_BRANCH + "let (r,g,b) = BUTTON_PALETTE",
        text, count=1)
    steps.append(("sysinfo background color", n))

    # 8. layer flag field
    text, n = re.subn(
        r"(    displays_battery: bool,\n)",
        r"\1    displays_sysinfo: bool,\n",
        text, count=1)
    steps.append(("displays_sysinfo field", n))

    text, n = re.subn(
        r"(        let displays_battery = cfg\.iter\(\)\.any\(\|cfg\| cfg\.battery\.is_some\(\)\);\n)",
        r"\1        let displays_sysinfo = cfg.iter().any(|cfg| cfg.sysinfo.is_some());\n",
        text, count=1)
    steps.append(("displays_sysinfo compute", n))

    text, n = re.subn(
        r"(        FunctionLayer \{\n            displays_time,\n            displays_battery,\n)",
        r"\1            displays_sysinfo,\n",
        text, count=1)
    steps.append(("displays_sysinfo init", n))

    # 9. refresh loop
    text, n = re.subn(
        r"        if layers\[active_layer\]\.displays_battery \{",
        lambda _: MAIN_LOOP_BLOCK,
        text, count=1)
    steps.append(("refresh loop", n))

    # 10. double press cycles through all layers
    text, n = re.subn(
        r"                                layers\.swap\(0, 1\);",
        "                                layers.rotate_left(1);\n"
        "                                needs_complete_redraw = true;",
        text, count=1)
    steps.append(("Fn double press rotates", n))

    return text, steps


EXAMPLE_TOML = '''# Append this to /etc/tiny-dfr/config.toml
# Two quick presses on Fn move to the next layer.

DoublePressSwitchLayers = 400

SystemLayerKeys = [
    { Sysinfo = "cpu", Stretch = 3 },
    { Sysinfo = "temp", Stretch = 3 },
    { Sysinfo = "mem", Stretch = 3 },
]
'''


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    root = os.path.expanduser(sys.argv[1])
    main_rs = os.path.join(root, "src", "main.rs")
    config_rs = os.path.join(root, "src", "config.rs")

    for p in (main_rs, config_rs):
        if not os.path.isfile(p):
            raise SystemExit(f"not found: {p}")

    if "--revert" in sys.argv:
        for p in (main_rs, config_rs):
            bak = p + ".layer3-backup"
            if os.path.isfile(bak):
                shutil.copy(bak, p)
                print("restored", p)
        return

    src_main = open(main_rs, encoding="utf-8").read()
    src_cfg = open(config_rs, encoding="utf-8").read()

    if "SysMetric" in src_main:
        raise SystemExit("already patched. use --revert first")
    if "BUTTON_PALETTE" not in src_main:
        raise SystemExit("colors patch missing - apply it first")

    shutil.copy(main_rs, main_rs + ".layer3-backup")
    shutil.copy(config_rs, config_rs + ".layer3-backup")

    out_cfg, steps_cfg = patch_config(src_cfg)
    out_main, steps_main = patch_main(src_main)

    failed = False
    for name, n in steps_cfg + steps_main:
        mark = "ok " if n else "FAIL"
        if not n:
            failed = True
        print(f"  [{mark}] {name}")

    if failed:
        print("\nsome steps did not apply, nothing was written")
        os.remove(main_rs + ".layer3-backup")
        os.remove(config_rs + ".layer3-backup")
        raise SystemExit(1)

    open(config_rs, "w", encoding="utf-8").write(out_cfg)
    open(main_rs, "w", encoding="utf-8").write(out_main)

    example = os.path.expanduser("~/system-layer-example.toml")
    open(example, "w", encoding="utf-8").write(EXAMPLE_TOML)

    print("\nall steps applied.")
    print("config snippet written to", example)
    print("\nnext:  cd", root, "&& cargo build --release")


if __name__ == "__main__":
    main()
