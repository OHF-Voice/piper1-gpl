graph TD;
    %% Subgraphs define logical groupings for clarity
    subgraph Build_Flow
        pip(pip) -- INVOKES --> setup_py["setup.py"];
        setup_py -- USES_TOOL --> skbuild["scikit-build"];
        skbuild -- INVOKES --> cmake["CMake"];
        cmake -- EXECUTES --> cmakelists["CMakeLists.txt"];
    end

    subgraph Quirks_Implementation_Details
        cmakelists -- IMPLEMENTS --> q_hybrid["Hybrid Build System"];
        setup_py -- IMPLEMENTS --> q_hybrid;

        cmakelists -- IMPLEMENTS --> q_pkg["CMake as Package Manager"];
        q_pkg -- USES_TOOL --> pkg["pkg / Termux"];

        cmakelists -- IMPLEMENTS --> q_self_build["Self-Contained Dependency Build"];
        cmakelists -- INSTRUCTS_BUILD_OF --> espeak["espeak-ng / local build"];
        q_self_build -- APPLIES_TO --> espeak;

        libpiper(libpiper) -- DEPENDS_ON --> espeak;
        espeakbridge(espeakbridge.c) -- DEPENDS_ON --> espeak;
    end

    %% Styling enhances readability by visually grouping node types
    classDef buildTool fill:#f9f,stroke:#333,stroke-width:2px;
    classDef component fill:#bbf,stroke:#333,stroke-width:2px;
    classDef quirk fill:#ff9,stroke:#333,stroke-width:2px,color:black;

    class pip,skbuild,cmake,pkg buildTool;
    class setup_py,cmakelists,libpiper,espeakbridge,espeak component;
    class q_hybrid,q_pkg,q_self_build quirk;
