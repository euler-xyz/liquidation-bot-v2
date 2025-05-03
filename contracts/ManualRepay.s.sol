// SPDX-License-Identifier: MIT

pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {Test} from "forge-std/Test.sol";
import {IERC20, IBorrowing} from "./IEVault.sol";

import "forge-std/console2.sol";

contract ManualRepay is Script {
    function run() public {
        uint256 liquidatorPrivateKey = vm.envUint("LIQUIDATOR_PRIVATE_KEY");

        address vaultAddress = 0xD8b27CF359b7D15710a5BE299AF6e7Bf904984C2;
        address assetAddress = 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2;

        address[] memory borrowers = new address[](1);
        borrowers[0] = 0xf47249e6a3D1326439316f23081810094BE53bfe;

        vm.startBroadcast(liquidatorPrivateKey);
        
        IERC20(assetAddress).approve(vaultAddress, type(uint256).max);

        for (uint256 i = 0; i < borrowers.length; i++) {    
            IBorrowing(vaultAddress).repay(type(uint256).max, borrowers[i]);
        }
    }
}
