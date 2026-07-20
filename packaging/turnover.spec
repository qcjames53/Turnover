Name:           turnover
Version:        0.1.0
Release:        1%{?dist}
Summary:        Send and receive iMessages in your terminal via Bluetooth

License:        GPL-3.0-or-later
URL:            https://github.com/qcjames53/Turnover
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz

BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros

%description
Send and receive iMessages in your terminal via Bluetooth.

Turnover syncs your iPhone's text messages and contacts over a Bluetooth MAP/PBAP connection.

%prep
%autosetup -p1 -n %{name}-%{version}
# Vendored nOBEX modules carry an upstream #!/usr/bin/env python shebang but
# aren't executable (they're imported, never run directly) -- vendoring
# policy is to keep src/turnover/_vendor/nobex/ byte-for-byte unmodified
# from upstream, so this is stripped here at build time rather than in the
# tracked source.
sed -i '1{/^#!/d}' src/turnover/_vendor/nobex/*.py

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files turnover

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_bindir}/turnover

%changelog
* Sat Jul 18 2026 Quinn James <qj@quinnjam.es> - 0.1.0-1
- Initial package
