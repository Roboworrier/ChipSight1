# ChipSight Deployment Guide

## Host Computer Setup

1. **Prerequisites**
   - Python 3.8 or higher installed
   - Git installed (optional)
   - Windows 10 or higher

2. **Installation Steps**

   a. Download and extract the ChipSight package
   b. Open Command Prompt as Administrator
   c. Navigate to the ChipSight directory
   d. Run the following commands:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **First-Time Setup**
   ```bash
   venv\Scripts\activate
   set FLASK_APP=app.py
   flask db upgrade
   ```

4. **Starting the Server**
   - Double-click `start_server.bat`
   - Keep the command window open
   - The server will be available at `http://[YOUR-IP]:5000`

## Client Computer Setup

1. **Requirements**
   - Must be on the same WiFi network as the host computer
   - Modern web browser (Chrome, Firefox, Edge recommended)

2. **Accessing ChipSight**
   a. Find the host computer's IP address:
      - On the host computer, open Command Prompt
      - Type `ipconfig`
      - Look for "IPv4 Address" under your WiFi adapter
   
   b. On client computers:
      - Open web browser
      - Enter `http://[HOST-IP]:5000`
      - Example: `http://192.168.1.100:5000`

## Security Notes

1. This setup is for internal network use only
2. Do not expose the server to the internet
3. Keep the host computer's Windows Firewall enabled
4. Ensure Windows is up to date on the host computer

## Troubleshooting

1. **Can't Connect to Server**
   - Verify host computer is running `start_server.bat`
   - Check if client is on the same network
   - Try pinging the host computer
   - Check Windows Firewall settings

2. **Server Won't Start**
   - Ensure no other service is using port 5000
   - Check if Python and all dependencies are installed
   - Verify database file exists

3. **Database Issues**
   - If database is corrupted, stop server
   - Delete `digital_twin.db`
   - Run `flask db upgrade` to create new database

## Maintenance

1. **Daily Operations**
   - Start server in the morning
   - Keep command window open
   - Close server at end of day

2. **Backups**
   - Regularly backup `digital_twin.db`
   - Keep copies of uploaded files
   - Document any configuration changes

3. **Updates**
   - Stop the server
   - Backup database
   - Update code
   - Run `pip install -r requirements.txt`
   - Run `flask db upgrade`
   - Restart server

For support: diwakar126796@gmail.com 