from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.build import check_min_cppstd
from conan.tools.cmake import CMake, CMakeDeps, CMakeToolchain, cmake_layout
from conan.tools.files import collect_libs, copy, get, save
import os


required_conan_version = ">=2.0"


class RmlUiConan(ConanFile):
    name = "rmlui"
    version = "6.1"
    package_type = "library"

    license = "MIT"
    homepage = "https://github.com/mikke89/RmlUi"
    url = "https://github.com/mikke89/RmlUi"
    description = "RmlUi is a C++ user interface library based on HTML/CSS."
    topics = ("ui", "html", "css")

    settings = "os", "arch", "compiler", "build_type"

    options = {
        "shared": [True, False],
        "fPIC": [True, False],

        # RmlUi 6.x feature toggles
        "build_samples": [True, False],
        "with_lua_bindings": [True, False],
        "font_engine": ["freetype", "none"],
        "matrix_row_major": [True, False],
        "with_thirdparty_containers": [True, False],
        "enable_precompiled_headers": [True, False],
        "enable_tracy_profiling": [True, False],
    }

    default_options = {
        "shared": False,
        "fPIC": True,

        "build_samples": False,
        "with_lua_bindings": False,
        "font_engine": "freetype",
        "matrix_row_major": False,
        "with_thirdparty_containers": True,
        "enable_precompiled_headers": True,
        "enable_tracy_profiling": False,
    }

    def layout(self):
        cmake_layout(self, src_folder="src")

    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC

    def validate(self):
        # Upstream supports older, but enforce a reasonable minimum for modern toolchains
        if self.settings.compiler.cppstd:
            check_min_cppstd(self, 14)

    def requirements(self):
        # Font engine dependency (docs mention RMLUI_FONT_ENGINE). :contentReference[oaicite:5]{index=5}
        if str(self.options.font_engine) == "freetype":
            self.requires("freetype/[>=2.10.4 <3]")

        # RmlUi can use external third-party containers (robin_hood + itlib).
        # Provide them to avoid <robin_hood.h> / <itlib/...> failures. :contentReference[oaicite:6]{index=6}
        if self.options.with_thirdparty_containers:
            self.requires("robin-hood-hashing/3.11.3")
            self.requires("itlib/1.11.4")

        # Optional Lua plugin (if you enable it, you likely want the Conan lua package)
        if self.options.with_lua_bindings:
            self.requires("lua/5.4.7")

    def source(self):
        # Self-contained download (no conandata.yml needed) — fixes your KeyError('sources').
        # Tag name is "6.1". :contentReference[oaicite:7]{index=7}
        src_url = f"https://github.com/mikke89/RmlUi/archive/refs/tags/{self.version}.tar.gz"

        # Strongly recommended: fill in sha256 for reproducibility.
        # Get it via: curl -L <url> | sha256sum
        sha256 = None

        get(self, url=src_url, sha256=sha256, strip_root=True)

        # Patch CMake to add include dirs for header-only deps when third-party containers are enabled.
        # This mirrors the approach used by vcpkg. :contentReference[oaicite:8]{index=8}
        core_cmake = os.path.join(self.source_folder, "Source", "Core", "CMakeLists.txt")
        with open(core_cmake, "r", encoding="utf-8") as f:
            content = f.read()

        marker = "unset(rmlui_core_TYPE)"
        helper_tag = "Conan helper: thirdparty container include dirs"
        if helper_tag not in content:
            if marker not in content:
                raise ConanInvalidConfiguration(
                    f"Upstream changed; cannot patch {core_cmake} (marker '{marker}' not found)"
                )

            injection = f"""
                # --- {helper_tag} ---
if(RMLUI_THIRDPARTY_CONTAINERS)
find_path(ROBIN_HOOD_INCLUDE_DIR robin_hood.h)
if(NOT ROBIN_HOOD_INCLUDE_DIR)
message(FATAL_ERROR "RmlUi: robin_hood.h not found. Provide robin-hood-hashing (e.g. via Conan).")
endif()
target_include_directories(rmlui_core PUBLIC ${{ROBIN_HOOD_INCLUDE_DIR}})

find_path(ITLIB_INCLUDE_DIR itlib/flat_map.hpp)
if(NOT ITLIB_INCLUDE_DIR)
message(FATAL_ERROR "RmlUi: itlib headers not found. Provide itlib (e.g. via Conan).")
endif()
target_include_directories(rmlui_core PUBLIC ${{ITLIB_INCLUDE_DIR}})
endif()
                # --- end {helper_tag} ---
                """
            content = content.replace(marker, marker + injection)
            save(self, core_cmake, content)

    def generate(self):
        deps = CMakeDeps(self)
        deps.generate()

        tc = CMakeToolchain(self)

        # Correct RmlUi 6.x CMake options. :contentReference[oaicite:9]{index=9}
        tc.variables["RMLUI_SAMPLES"] = bool(self.options.build_samples)
        tc.variables["RMLUI_LUA_BINDINGS"] = bool(self.options.with_lua_bindings)
        tc.variables["RMLUI_FONT_ENGINE"] = str(self.options.font_engine)
        tc.variables["RMLUI_MATRIX_ROW_MAJOR"] = bool(self.options.matrix_row_major)
        tc.variables["RMLUI_THIRDPARTY_CONTAINERS"] = bool(self.options.with_thirdparty_containers)
        tc.variables["RMLUI_PRECOMPILED_HEADERS"] = bool(self.options.enable_precompiled_headers)
        tc.variables["RMLUI_TRACY_PROFILING"] = bool(self.options.enable_tracy_profiling)

        # Avoid CI-only footguns
        tc.variables["RMLUI_WARNINGS_AS_ERRORS"] = False

        tc.generate()

    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def package(self):
        cmake = CMake(self)
        cmake.install()
        copy(self, "LICENSE*", src=self.source_folder, dst=os.path.join(self.package_folder, "licenses"), keep_path=False)

    def package_info(self):
        # Consumers expect find_package(RmlUi) and target RmlUi::RmlUi. :contentReference[oaicite:10]{index=10}
        self.cpp_info.set_property("cmake_file_name", "RmlUi")
        self.cpp_info.set_property("cmake_target_name", "RmlUi::RmlUi")

        # Don’t guess library names; collect what was installed.
        self.cpp_info.libs = collect_libs(self)

        if not self.options.shared:
            self.cpp_info.defines.append("RMLUI_STATIC_LIB")

