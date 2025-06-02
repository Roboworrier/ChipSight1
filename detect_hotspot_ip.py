import subprocess
import re

def get_hotspot_ip():
    # Run the ARP command to get the list of connected devices
    result = subprocess.run(['arp', '-a'], capture_output=True, text=True)
    arp_output = result.stdout

    # Parse the ARP table to find dynamic entries (likely connected devices)
    ip_pattern = re.compile(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+([0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2}\s+dynamic')
    matches = ip_pattern.findall(arp_output)

    if matches:
        # Return the first dynamic IP (likely the phone)
        return matches[0][0]
    else:
        return None

if __name__ == "__main__":
    hotspot_ip = get_hotspot_ip()
    if hotspot_ip:
        print(f"Detected hotspot device IP: {hotspot_ip}")
    else:
        print("No dynamic IP found in ARP table. Ensure your phone is connected to the hotspot.")