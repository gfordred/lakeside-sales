# Lakeside Village - Quick Deployment Guide

## 🚀 Deploy to Streamlit Cloud (Free)

### Prerequisites
- GitHub account
- Streamlit Cloud account (free at https://streamlit.io/cloud)

### Steps

1. **Push to GitHub**
   ```bash
   cd lakeside-sales-py
   git init
   git add .
   git commit -m "Initial commit - Lakeside property sales map"
   git remote add origin https://github.com/YOUR_USERNAME/lakeside-sales.git
   git push -u origin main
   ```

2. **Deploy on Streamlit Cloud**
   - Go to https://share.streamlit.io
   - Click "New app"
   - Select your repository
   - Set main file path: `app.py`
   - Click "Deploy"

3. **Configure Environment Variables**
   - In Streamlit Cloud dashboard, go to App settings
   - Add secrets:
     ```toml
     GOOGLE_SHEETS_URL = "your_sheet_url"
     CONTACT_EMAIL = "info@lakesidevillage.com"
     ```

4. **Done!**
   - Your app will be live at: `https://YOUR_APP_NAME.streamlit.app`
   - Auto-deploys on every git push

---

## 🔧 Local Development

```bash
# Setup
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt

# Run
streamlit run app.py

# Access at http://localhost:8501
```

---

## 📊 Features Included

✅ Interactive property map with site plan background  
✅ Real-time Google Sheets integration  
✅ Search and filter by status  
✅ Property details panel  
✅ Dark theme UI  
✅ Analytics tracking  
✅ Mobile responsive  
✅ Contact agent button  

---

## 🎨 Customization

### Change Colors
Edit `.streamlit/config.toml`:
```toml
[theme]
primaryColor = "#2ecc71"  # Change to your brand color
```

### Update Google Sheets
Edit `.env`:
```bash
GOOGLE_SHEETS_URL=your_new_url
```

### Modify Status Colors
Edit `config/settings.py`:
```python
STATUS_CONFIG = {
    "available": {"color": "#yourcolor", ...}
}
```

---

## 📈 Analytics

View analytics data in `data/cache/analytics.json`:
- Property views
- Search queries
- Contact button clicks
- Session tracking

---

## 🆘 Troubleshooting

**Map not showing?**
- Check `data/polygons.json` exists
- Verify `assets/images/site_plan.jpg` exists

**Data not loading?**
- Verify Google Sheets URL is correct
- Check sheet is published to web
- Ensure CSV output format

**Slow performance?**
- Clear cache: Settings → Clear cache
- Reduce image size in `assets/images/`

---

## 📞 Support

Questions? Contact: info@lakesidevillage.com
