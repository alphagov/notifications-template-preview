#!/usr/bin/env bash

# usage: choom-wrap-pkgs <adjustment> <pkg_name> ...
# wraps binaries belonging to listed debian packages
# in a choom(1) call making adjustment <adjustment>
# to the process's oom score when executed.

function choom_wrap_bin() {
  local adjustment="$1"; shift
  local bin_path="$1"; shift
  echo "choom-wrapping ${bin_path} with adjustment ${adjustment}" >&2

  local bin_basename="$(basename ${bin_path})"
  local bin_dirname="$(dirname ${bin_path})"
  local bin_newpath="${bin_dirname}/.${bin_basename}-wrapped"

  mv "${bin_path}" "${bin_newpath}"

  cat > "${bin_path}" <<EOF
#!/usr/bin/env bash
exec choom -n '${adjustment}' -- '${bin_newpath}' "\$@"
EOF
  chmod --reference="${bin_newpath}" "${bin_path}"
}

function choom_wrap_deb_pkg() {
  local adjustment="$1"; shift
  local pkg_name="$1"; shift
  echo "choom-wrapping binaries from debian package ${pkg_name}" >&2

  dpkg -L "${pkg_name}" | while read -r filepath ; do
    if [ -f "${filepath}" -a -x "${filepath}" ] ; then
      choom_wrap_bin "${adjustment}" "${filepath}"
    fi
  done
}

function choom_wrap_deb_pkgs() {
  local adjustment="$1"; shift
  for pkg_name in "$@" ; do
    choom_wrap_deb_pkg "${adjustment}" "${pkg_name}"
  done
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  choom_wrap_deb_pkgs "$@"
fi
