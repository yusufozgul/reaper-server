#!/usr/bin/env python3

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


def extract_aab(aab_path, output_dir):
  print(f"Extracting {aab_path} to {output_dir}...")
  with zipfile.ZipFile(aab_path, "r") as zip_ref:
    zip_ref.extractall(output_dir)

  base_module_path = os.path.join(output_dir, "base")
  if os.path.exists(base_module_path):
    base_zips = []
    for root, dirs, files in os.walk(base_module_path):
      for file in files:
        if file.endswith(".zip"):
          base_zips.append(os.path.join(root, file))

    for base_zip in base_zips:
      base_dir = os.path.dirname(base_zip)
      with zipfile.ZipFile(base_zip, "r") as zip_ref:
        zip_ref.extractall(base_dir)

  return output_dir


def find_dex_files(extract_dir):
  dex_files = []
  for root, dirs, files in os.walk(extract_dir):
    for file in files:
      if file.endswith(".dex"):
        dex_files.append(os.path.join(root, file))

  if dex_files:
    print(f"Found {len(dex_files)} DEX files.")
  else:
    print("No DEX files found in the extracted AAB.")

  return dex_files


def extract_smali(dex_files, output_dir):
  for dex_file in dex_files:
    dex_basename = os.path.basename(dex_file)
    smali_output = os.path.join(output_dir, f"smali_{dex_basename}")
    os.makedirs(smali_output, exist_ok=True)

    print(f"Extracting smali from {dex_file} to {smali_output}...")
    try:
      subprocess.run(
        ["baksmali", "disassemble", dex_file, "-o", smali_output],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
      )
      yield smali_output
    except subprocess.CalledProcessError as e:
      print(f"Error extracting smali from {dex_file}: {e}")
      stdout = e.stdout.decode("utf-8", errors="replace")
      stderr = e.stderr.decode("utf-8", errors="replace")
      print(f"stdout: {stdout}")
      print(f"stderr: {stderr}")
    except FileNotFoundError:
      print("Error: baksmali tool not found. Please make sure it's installed and in your PATH.")
      sys.exit(1)


def find_proguard_maps(extract_dir):
  """Find any ProGuard mapping files in the extracted AAB."""
  proguard_maps = []
  for root, dirs, files in os.walk(extract_dir):
    for file in files:
      if file == "mapping.txt":
        proguard_maps.append(os.path.join(root, file))

  if proguard_maps:
    print(f"Found {len(proguard_maps)} ProGuard mapping files.")
  else:
    print("No ProGuard mapping files found.")

  return proguard_maps


def load_proguard_mapping(proguard_map_file):
  """Load the ProGuard mapping file into a dictionary."""
  mapping = {}

  if not proguard_map_file:
    return mapping

  try:
    with open(proguard_map_file, "r", encoding="utf-8", errors="replace") as f:
      current_class = None

      for line in f:
        line = line.strip()

        if not line:
          continue

        if not line.startswith(" "):
          class_match = re.match(r"([\w\./$]+) -> ([\w\./$]+):", line)
          if class_match:
            original_class = class_match.group(1)
            obfuscated_class = class_match.group(2)
            current_class = original_class
            mapping[obfuscated_class] = original_class

  except Exception as e:
    print(f"Error reading ProGuard mapping file {proguard_map_file}: {e}")

  return mapping


def extract_class_signatures_from_smali(smali_dir, proguard_mapping):
  for root, dirs, files in os.walk(smali_dir):
    for file in files:
      if file.endswith(".smali"):
        smali_path = os.path.join(root, file)

        with open(smali_path, "r", encoding="utf-8", errors="replace") as f:
          content = f.read()
        lines = content.split("\n")

        for line in lines:
          if line.startswith(".class"):
            obfuscated_class = line.split(" ").pop()

            sha256_binary = hashlib.sha256(obfuscated_class.encode()).digest()
            sha256_hash = binascii.hexlify(sha256_binary).decode()

            top_64_bits = sha256_binary[:8]
            base64_top_64 = base64.b64encode(top_64_bits).decode()

            yield (obfuscated_class, sha256_hash, base64_top_64)
            break


def process_aab_file(aab_file):
  temp_dir = tempfile.mkdtemp(prefix="reaper_upload_")
  temp_file_path = os.path.join(temp_dir, aab_file.filename)

  try:
    aab_file.save(temp_file_path)
    return process_aab_file_path(temp_file_path)
  finally:
    if os.path.exists(temp_dir):
      shutil.rmtree(temp_dir, ignore_errors=True)


def extract_aab_metadata(aab_file_path):
  """
  Extract metadata from AAB file using bundletool.

  Args:
      aab_file_path: Path to the AAB file

  Returns:
      A dictionary containing package name, version code and version name
  """
  metadata = {"package_name": None, "version_code": None, "version_name": None}

  try:
    # Extract package name
    result = subprocess.run(
      [
        "bundletool",
        "dump",
        "manifest",
        "--bundle",
        aab_file_path,
        "--xpath",
        "/manifest/@package",
      ],
      check=True,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      text=True,
    )
    if result.stdout.strip():
      metadata["package_name"] = result.stdout.strip()

    # Extract version code
    result = subprocess.run(
      [
        "bundletool",
        "dump",
        "manifest",
        "--bundle",
        aab_file_path,
        "--xpath",
        "/manifest/@android:versionCode",
      ],
      check=True,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      text=True,
    )
    if result.stdout.strip():
      metadata["version_code"] = result.stdout.strip()

    # Extract version name
    result = subprocess.run(
      [
        "bundletool",
        "dump",
        "manifest",
        "--bundle",
        aab_file_path,
        "--xpath",
        "/manifest/@android:versionName",
      ],
      check=True,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      text=True,
    )
    if result.stdout.strip():
      metadata["version_name"] = result.stdout.strip()

    print(f"Extracted metadata: {json.dumps(metadata, indent=2)}")
    return metadata

  except subprocess.CalledProcessError as e:
    print(f"Error extracting metadata: {e}")
    print(f"stdout: {e.stdout}")
    print(f"stderr: {e.stderr}")
    return metadata
  except FileNotFoundError:
    print("Error: bundletool not found. Please make sure it's installed and in your PATH.")
    return metadata


def process_aab_file_path(aab_file_path):
  """
  Process an AAB file and return a list of class signatures.

  Args:
      aab_file_path: Path to the AAB file

  Returns:
      A list of tuples (class_signature, sha256, base64_top_64)
  """
  if not os.path.exists(aab_file_path):
    raise FileNotFoundError(f"AAB file {aab_file_path} does not exist.")

  temp_dir = tempfile.mkdtemp(prefix="aab_extract_")
  results = []

  try:
    # Extract app metadata
    metadata = extract_aab_metadata(aab_file_path)

    extract_dir = extract_aab(aab_file_path, temp_dir)

    dex_files = find_dex_files(extract_dir)
    if not dex_files:
      return []

    proguard_maps = find_proguard_maps(extract_dir)
    proguard_mapping = {}
    if proguard_maps:
      proguard_mapping = load_proguard_mapping(proguard_maps[0])

    smali_output_dir = os.path.join(temp_dir, "smali_output")
    os.makedirs(smali_output_dir, exist_ok=True)

    app_id = metadata.get("package_name", "unknown")
    version = metadata.get("version_name", "unknown")

    for smali_dir in extract_smali(dex_files, smali_output_dir):
      for class_sig, sha256, base64_top_64 in extract_class_signatures_from_smali(
        smali_dir, proguard_mapping
      ):
        # Include app_id and version in the results
        results.append((class_sig, sha256, base64_top_64, app_id, version))

    return results

  finally:
    shutil.rmtree(temp_dir, ignore_errors=True)


def main():
  parser = argparse.ArgumentParser(description="Extract class signatures from an Android AAB file")
  parser.add_argument("aab_file", help="Path to the Android AAB file")
  parser.add_argument("-o", "--output", help="Output file for class signatures")
  args = parser.parse_args()

  try:
    results = process_aab_file_path(args.aab_file)

    if args.output:
      with open(args.output, "w") as f:
        for class_sig, sha256, base64_top_64, app_id, version in results:
          f.write(f"{class_sig}\t{sha256}\t{base64_top_64}\t{app_id}\t{version}\n")
    else:
      for class_sig, sha256, base64_top_64, app_id, version in results:
        print(f"{class_sig}\t{sha256}\t{base64_top_64}\t{app_id}\t{version}")

  except Exception as e:
    print(f"Error: {str(e)}")
    sys.exit(1)


if __name__ == "__main__":
  main()
