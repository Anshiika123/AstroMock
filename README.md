# AstroMock

A small Flask API that generates a Vedic birth chart (Kundali) from a date, time, and place of birth.

- Sidereal zodiac with Lahiri Ayanamsha, Whole Sign houses, mean node for Rahu/Ketu (via [pyswisseph](https://pypi.org/project/pyswisseph/))
- Geocoding and timezone resolution via Nominatim (OpenStreetMap) and [timezonefinder](https://pypi.org/project/timezonefinder/)

## Setup

```bash
pip install -r requirements.txt
python app.py
```

## API

`POST /api/kundali`

```json
{
  "date_of_birth": "1990-01-15",
  "time_of_birth": "14:30",
  "place_of_birth": "Mumbai, India",
  "unsure_of_time": false
}
```

Returns the resolved birth location and the calculated Kundali chart.

## License

MIT — see [LICENSE](LICENSE).
