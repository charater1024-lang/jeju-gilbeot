[out:json][timeout:45][maxsize:67108864];
(
  nwr["tourism"~"^(attraction|museum|viewpoint|artwork|theme_park|zoo|gallery)$"](32.9,126.0,33.7,127.0);
  nwr["natural"~"^(peak|beach|cave_entrance|volcano)$"](32.9,126.0,33.7,127.0);
  nwr["leisure"~"^(park|garden|nature_reserve)$"](32.9,126.0,33.7,127.0);
  nwr["historic"]["name"](32.9,126.0,33.7,127.0);
);
out meta center;
