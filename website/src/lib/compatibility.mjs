// Requirements checked against NotRexed/Hookshot's README on 2026-11-10.
// Keep hardware requirements separate from performance and stability claims.
export function checkCompatibility(input) {
  const rows = [];
  const add = (level, title, text) => rows.push({ level, title, text });
  if (input.game === 'supported') add('pass', 'Game version', 'The selected version matches program 0400486024DEC000, update v131072, build e0f3ccfa. Hookshot Builder must still validate your copy.');
  else if (input.game === 'other') add('block', 'Game version', 'Other game versions are not supported. Use your own copy with the supported update and build.');
  else add('unknown', 'Game version', 'Check your copy in Hookshot Builder. The supported version is program 0400486024DEC000, update v131072, build e0f3ccfa.');

  if (input.os === 'windows') add('pass', 'Operating system', '64-bit Windows 10 and 11 are listed as supported.');
  else if (input.os === 'linux-appimage' || input.os === 'linux-source') {
    if (input.glibc === 'yes') add('pass', 'Linux system libraries', 'glibc 2.35 or newer matches the documented requirement.');
    else if (input.glibc === 'no') add('block', 'Linux system libraries', 'The documented Linux build needs glibc 2.35 or newer.');
    else add('unknown', 'Linux system libraries', 'Check your glibc version with ldd --version. The documented requirement is 2.35 or newer.');
    if (input.os === 'linux-appimage') {
      if (input.avx2 === 'yes') add('pass', 'AppImage CPU support', 'Your selected CPU capability meets the AVX2 requirement.');
      else if (input.avx2 === 'no') add('block', 'AppImage CPU support', 'The Linux AppImage requires AVX2. The README describes building from source for CPUs without it.');
      else add('unknown', 'AppImage CPU support', 'Check your CPU specifications for AVX2 before using the Linux AppImage.');
    } else add('note', 'Source build', 'A source build can target a CPU without AVX2. Follow the Linux build instructions for toolchain dependencies.');
  } else if (input.os === 'other') add('block', 'Operating system', 'The documented platforms are 64-bit Windows 10/11 and 64-bit Linux. This selection is outside those platforms.');
  else add('unknown', 'Operating system', 'Select your operating system and, for Linux, how you plan to build.');

  const families = {
    nvidia: ['pass', 'GeForce RTX 20 series and newer are in the documented GPU range. NVIDIA is the most tested vendor.'],
    amd: ['warning', 'Radeon RX 6000 series and newer are in the documented GPU range. Some AMD cards have known crashes and rendering problems.'],
    intel: ['warning', 'Intel Arc is in the documented GPU range, but reports are limited and include black screens and crashes.'],
    deck: ['warning', 'Steam Deck reports include freezes and missing geometry. Check the Linux/Steam Deck issue tracker before building.'],
    legacy: ['block', 'Cards without mesh shaders are not supported. The compute fallback can leave parts of the picture missing.'],
  };
  const gpu = families[input.gpu];
  add(gpu?.[0] ?? 'unknown', 'Graphics card', gpu?.[1] ?? 'Check your GPU specifications and driver for Vulkan 1.3 and mesh shaders. An unlisted model is not automatically incompatible.');
  if (input.driver === 'yes') add('pass', 'Driver capabilities', 'You confirmed an up-to-date driver with Vulkan 1.3 and mesh shaders. This tool cannot verify the installed driver.');
  else if (input.driver === 'no') add('block', 'Driver capabilities', 'The supported rendering path needs Vulkan 1.3 and mesh shaders. Update the driver and check again; a driver update cannot add missing hardware features.');
  else add('unknown', 'Driver capabilities', 'Confirm Vulkan 1.3 and mesh-shader support with your installed driver. On Linux, vulkaninfo should list VK_EXT_mesh_shader.');

  for (const [key, title, target, low, pass] of [
    ['ram', 'System memory', 16, 'Below the documented 16 GB RAM requirement. A run uses about 10 GB, with the OS and other apps needing memory too.', 'Meets the documented 16 GB RAM requirement.'],
    ['vram', 'Video memory', 8, 'Below the recommended 8 GB VRAM. Lower Quality presets may help; this does not establish that your GPU will work.', 'Meets the 8 GB VRAM recommendation.'],
    ['disk', 'Free build space', 60, 'The build needs about 60 GB free. Free up space before starting; the exact amount can vary.', 'Meets the approximate 60 GB build-space allowance. An SSD is recommended.'],
  ]) {
    const raw = input[key];
    const value = Number(raw);
    if (raw == null || String(raw).trim() === '' || !Number.isFinite(value) || value <= 0) add('unknown', title, `Enter the available ${title.toLowerCase()} in GB to check it.`);
    else add(value < target ? 'warning' : 'pass', title, value < target ? low : pass);
  }
  const status = rows.some(r => r.level === 'block') ? 'block'
    : rows.some(r => r.level === 'unknown') ? 'unknown'
    : rows.some(r => r.level === 'warning') ? 'warning' : 'pass';
  const titles = { block: 'Outside the supported requirements', unknown: 'More details needed', warning: 'Requirements need attention', pass: 'Matches the listed requirements' };
  return { status, title: titles[status], rows };
}
